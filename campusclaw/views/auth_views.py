"""登录/退出视图：服务端会话的创建与撤销。"""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from campusclaw import request_context as rc
from campusclaw import security, sessions
from campusclaw.config import DEFAULT_SEED_PASSWORDS, SEED_ACCOUNTS
from campusclaw.errors import MESSAGES, ApiError, audit_rejection

bp = Blueprint("auth", __name__)

#: 登录页的预置账号速填卡片。只用于展示内置演示凭据，不参与任何鉴权判定。
_AVATARS = {
    ("teacher", "A"): "👩‍🏫",
    ("student", "A"): "🧑‍🎓",
    ("student", "B"): "👧",
    ("teacher", "B"): "👨‍🏫",
}

DEMO_ACCOUNTS = [
    {
        "username": account.username,
        "password": DEFAULT_SEED_PASSWORDS[account.username],
        "role": "教师" if account.role == "teacher" else "学生",
        "class_name": account.class_name,
        "emoji": _AVATARS.get((account.role, account.class_name), "👤"),
    }
    for account in SEED_ACCOUNTS
]


@bp.get("/login")
def login_page():
    token = rc.ensure_csrf_token()
    return render_template("login.html", csrf_token=token, accounts=DEMO_ACCOUNTS)


def _render_login_failure(
    status: int, code: str, message: str, username: str = ""
) -> tuple[str, int]:
    """登录表单失败：回到登录页说人话，不要把 JSON 甩到浏览器里。

    ``/api/auth/login`` 是给程序调用的，那里继续走 ``ApiError`` 的 JSON 分支；
    页面表单是给人用的，两类请求不该共用一个出口。分流之前，输错一次密码
    就会在屏幕上看到 ``{"error":{"code":"INVALID_CREDENTIALS"...}}``。

    错误码变化（比如 CSRF 过期）也要回登录页——这正是普通人最常撞的一种。
    """
    audit_rejection(status, code, message)
    return (
        render_template(
            "login.html",
            csrf_token=rc.ensure_csrf_token(),
            accounts=DEMO_ACCOUNTS,
            error=message,
            username=username,
        ),
        status,
    )


@bp.post("/login")
def login():
    # 顺序：CSRF → 撤销旧会话 → 输入校验 → 口令校验 → 建立新会话。
    rc.reject_identity_fields()
    if not security.tokens_equal(
        str(session.get(rc.CSRF_FIELD) or ""), str(rc.submitted_csrf_token() or "")
    ):
        return _render_login_failure(
            403,
            "CSRF_INVALID",
            "页面已过期，请重新登录",
            (request.form.get("username") or "").strip(),
        )

    conn = rc.get_conn()
    rc.revoke_current_session(conn)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if username == "" or password == "":
        return _render_login_failure(
            400, "INVALID_INPUT", "请输入账号和密码", username
        )

    user = rc.get_conn().execute(
        "SELECT id, username, password_hash, role, class_id FROM users WHERE username = ?",
        (username,),
    ).fetchone()

    if user is None or not security.verify_password(password, user["password_hash"]):
        # 不区分账号是否存在，统一 401 提示。
        return _render_login_failure(
            401, "INVALID_CREDENTIALS", "账号或密码错误", username
        )

    from campusclaw.timeutil import now_utc

    sid = sessions.create_session(
        conn, int(user["id"]), now_utc(), rc.get_settings().session_hours
    )
    session.clear()
    session["sid"] = sid
    rc.rotate_csrf_token()
    return redirect(url_for("pages.materials_page"), code=302)


@bp.post("/logout")
def logout():
    rc.require_api_auth()
    rc.require_csrf()
    conn = rc.get_conn()
    sessions.revoke_session(conn, session.get("sid"))
    session.clear()
    rc.ensure_csrf_token()
    return redirect(url_for("auth.login_page"), code=302)


@bp.get("/api/csrf")
def csrf_token_api():
    """取当前会话的 CSRF 令牌，供前端在令牌过期时自愈重试。

    GET 不校验令牌（它本身就是发令牌的），但要先登录——未登录的请求不该
    拿到任何会话内标识。页面上那个令牌是渲染时写死的，页面开久了两处会
    对不上：实测里「第一次上传 403 CSRF_INVALID、刷新后同样的操作 201」
    就是这种时间差造成的，用户只会觉得「点了没反应」。
    """
    rc.require_api_auth()
    return jsonify({"csrf_token": rc.ensure_csrf_token()}), 200
