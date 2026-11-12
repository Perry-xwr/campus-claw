"""HTTP 层身份、角色、班级与 CSRF 判定。

客户端提交的 class_id / role / user_id / uploaded_by 均为身份字段，不能用作授权依据。
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from typing import Any, Mapping

from flask import Flask, g, jsonify, redirect, request, session, url_for

from campusclaw import audit_db, db as dbmod, metrics, security, sessions
from campusclaw.errors import MESSAGES, ApiError, error_body

logger = logging.getLogger(__name__)

IDENTITY_FIELDS = frozenset({"class_id", "role", "user_id", "uploaded_by"})

CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"


def get_settings() -> Any:
    from flask import current_app

    return current_app.extensions["campusclaw"]["settings"]


def get_conn() -> sqlite3.Connection:
    if "db" not in g:
        g.db = dbmod.connect(get_settings().db_path)
    return g.db


def close_conn(_exc: BaseException | None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


BEARER_SCHEME = "Bearer "


def _bearer_token() -> str | None:
    """从 Authorization 头取 Bearer 令牌；方案不符或令牌为空/含空格时返回 None。"""
    header = request.headers.get("Authorization") or ""
    if not header.startswith(BEARER_SCHEME):
        return None
    token = header[len(BEARER_SCHEME):].strip()
    if not token or " " in token:
        return None
    return token


def current_user() -> dict[str, Any] | None:
    """读取本次请求的服务端身份上下文；不信任任何客户端字段。

    优先 Bearer 令牌（API 客户端），回退签名 Cookie 会话（浏览器页面）。
    """
    if "user" in g:
        return g.user
    token = _bearer_token()
    if token is not None:
        user = sessions.load_session_user(get_conn(), token)
        g.user = dict(user) if user is not None else None
        g.bearer_auth = True
        return g.user
    g.bearer_auth = False
    user = sessions.load_session_user(get_conn(), session.get("sid"))
    g.user = dict(user) if user is not None else None
    return g.user


def using_bearer_auth() -> bool:
    """本次请求是否以 Bearer 令牌认证（决定写接口是否免 CSRF）。"""
    if "bearer_auth" not in g:
        current_user()
    return bool(g.get("bearer_auth"))


def current_sid() -> str | None:
    """本次请求携带的会话标识：Bearer 令牌或 Cookie sid。"""
    token = _bearer_token()
    return token if token is not None else session.get("sid")


def require_page_auth():
    """受保护页面：未认证重定向到登录页。"""
    user = current_user()
    if user is None:
        raise ApiError(302, "AUTH_REQUIRED", MESSAGES["AUTH_REQUIRED"])
    return user


def require_api_auth():
    """受保护 API：未认证固定 401 JSON。"""
    user = current_user()
    if user is None:
        raise ApiError(401, "AUTH_REQUIRED", MESSAGES["AUTH_REQUIRED"])
    return user


def revoke_current_session(conn: Any) -> None:
    """撤销本次携带的会话失效，并清理缓存到的请求上下文。"""
    sessions.revoke_session(conn, current_sid())
    session.pop("sid", None)
    g.pop("user", None)


def ensure_csrf_token() -> str:
    """保证当前会话持有 CSRF token；匿名会话也持有，用于登录表单。"""
    token = session.get(CSRF_FIELD)
    if not token:
        token = security.new_csrf_token()
        session[CSRF_FIELD] = token
    return token


def rotate_csrf_token() -> str:
    """登录成功后轮换 token。"""
    token = security.new_csrf_token()
    session[CSRF_FIELD] = token
    return token


def submitted_csrf_token() -> str | None:
    return request.headers.get(CSRF_HEADER) or request.form.get(CSRF_FIELD)


def require_csrf() -> None:
    """写接口 CSRF 校验失败返回 403，且不产生任何写入副作用。

    Bearer 令牌请求不要求 CSRF：令牌由客户端显式携带，不随浏览器自动发送，
    不存在跨站伪造面；Cookie 会话仍强制校验。
    """
    if using_bearer_auth():
        return
    expected = session.get(CSRF_FIELD)
    provided = submitted_csrf_token()
    if not security.tokens_equal(str(expected or ""), str(provided or "")):
        raise ApiError(403, "CSRF_INVALID", MESSAGES["CSRF_INVALID"])


def require_write():
    """写顺序：认证 → 角色检查 → CSRF。角色拒绝优先于资源是否存在。"""
    user = require_api_auth()
    if user["role"] != "teacher":
        raise ApiError(403, "ROLE_FORBIDDEN", MESSAGES["ROLE_FORBIDDEN"])
    require_csrf()
    return user


def require_write_any():
    """任意已登录用户的写接口：认证 → CSRF（不限制角色）。

    学生可创建会话、发送消息，同样属于骑在 Cookie 上的状态变更，
    必须过 CSRF；Bearer 令牌请求按 require_csrf 的约定豁免。
    """
    user = require_api_auth()
    require_csrf()
    return user


def iter_identity_violations(json_body: Mapping[str, Any] | None = None) -> list[str]:
    """扫描 query / form / JSON 中的身份字段。"""
    found: list[str] = []
    sources: tuple[tuple[str, Mapping[str, Any]], ...] = (
        ("query", request.args),
        ("form", request.form),
    )
    if json_body is not None:
        sources = sources + (("json", json_body),)
    for source_name, values in sources:
        for key in values.keys():
            if key.lower() in IDENTITY_FIELDS:
                found.append(f"{source_name}:{key}")
    return found


def reject_identity_fields(json_body: Mapping[str, Any] | None = None) -> None:
    violations = iter_identity_violations(json_body)
    if violations:
        raise ApiError(
            400, "IDENTITY_FIELD_FORBIDDEN", MESSAGES["IDENTITY_FIELD_FORBIDDEN"]
        )


def register_page_redirect(app: Flask) -> None:
    """未认证访问受保护页面时重定向；API 错误不得被重定向为 HTML。"""

    @app.errorhandler(ApiError)
    def _handle(exc: ApiError):
        # SEC-07：拒绝也要留痕，先记审计再返回响应。
        audit_rejected_request(exc.status, exc.code, exc.message)
        if exc.status == 302 and not _is_api_request():
            session.pop("sid", None)
            return redirect(url_for("auth.login_page"))
        return jsonify(error_body(exc.code, exc.message)), exc.status

    def _is_api_request() -> bool:
        path = request.path or ""
        return path.startswith("/api/") or path.startswith("/health")


def upload_identity_check(form: Mapping[str, Any]) -> None:
    """上传表单专用：身份字段优先于未知字段判定。"""
    for key in form.keys():
        if key.lower() in IDENTITY_FIELDS:
            raise ApiError(
                400, "IDENTITY_FIELD_FORBIDDEN", MESSAGES["IDENTITY_FIELD_FORBIDDEN"]
            )


# ---------------------------------------------------------------------------
# 第 9 课 SEC-07：请求标识与拒绝审计
#
# 课件要求「失败的尝试也要记」：401 / 403 / 404 正是越权与探测的证据。
# 这里在统一错误出口处落一条结构化事件，best-effort，失败不影响响应。
# ---------------------------------------------------------------------------

REQUEST_ID_HEADER = "X-Request-Id"


def register_request_tracking(app: Flask) -> None:
    """为每个请求生成贯穿全链路的 request_id，并回写到响应头。"""

    @app.before_request
    def _assign_request_id() -> None:
        incoming = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
        # 客户端可带，但一律截断：不能让外部输入撑坏日志字段或撑爆内存。
        g.request_id = (incoming[:64] if incoming else f"req-{uuid.uuid4().hex[:12]}")
        g.request_started = time.perf_counter()

    @app.after_request
    def _echo_request_id(response):
        request_id = getattr(g, "request_id", "")
        if request_id:
            response.headers.setdefault(REQUEST_ID_HEADER, request_id)
        # 第 10 课：把本次请求计入指标；/metrics 自身不计数，避免抓取把曲线拉平。
        if not (request.path or "").startswith("/metrics"):
            try:
                metrics.observe_from_g(g, response.status_code)
            except Exception:  # pragma: no cover - 指标失败绝不影响响应
                logger.exception("记录请求指标失败")
        return response


def _request_duration_ms() -> int | None:
    started = getattr(g, "request_started", None)
    if started is None:
        return None
    return int(round((time.perf_counter() - started) * 1000))


def _actor_snapshot() -> tuple[int | None, str, int | None]:
    """取当前操作人；未认证或被拒绝的请求没有身份，返回空值而不是抛错。"""
    try:
        user = current_user()
    except Exception:  # pragma: no cover - 身份解析异常不得影响审计出口
        return None, "", None
    if not user:
        return None, "", None
    try:
        actor_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        actor_id = None
    try:
        class_id = int(user["class_id"])
    except (KeyError, TypeError, ValueError):
        class_id = None
    return actor_id, str(user.get("username") or ""), class_id


def audit_rejected_request(status: int, code: str, detail: str = "") -> None:
    """把一次被拒绝的请求记入 audit_events。

    只记认证/授权类拒绝（401/403）与跨班不可见（404）：这三类是攻击证据；
    参数校验类 400 数量大、价值低，不在此列，避免日志被噪声淹没。
    同一请求最多记一次（错误处理器可能被叠加注册）。
    """
    try:
        if status not in audit_db.REJECT_STATUSES:
            return
        if getattr(g, "_audit_rejection_logged", False):
            return
        g._audit_rejection_logged = True
        actor_id, actor, class_id = _actor_snapshot()
        audit_db.record_event(
            get_conn(),
            status=status,
            code=code,
            action="api.reject",
            actor=actor,
            actor_id=actor_id,
            class_id=class_id,
            object_type="api",
            object_id=f"{request.method} {request.path}",
            method=request.method,
            path=request.path,
            request_id=str(getattr(g, "request_id", "") or ""),
            duration_ms=_request_duration_ms(),
            detail=detail,
        )
    except Exception:
        # 审计不得影响主流程：磁盘满、表缺失等一律降级为应用日志。
        logger.exception("写入拒绝审计失败：%s %s", status, code)
