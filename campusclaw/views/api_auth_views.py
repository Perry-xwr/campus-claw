"""Bearer 令牌 API：JSON 登录、登出与当前身份。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from campusclaw import request_context as rc, security, sessions
from campusclaw.errors import ApiError, MESSAGES

bp = Blueprint("api_auth", __name__)


@bp.post("/api/login")
def api_login():
    """JSON 登录：校验口令后复用服务端会话表签发 Bearer 令牌。"""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_INPUT", "请求必须是 JSON")
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ApiError(400, "INVALID_INPUT", MESSAGES["INVALID_INPUT"])

    conn = rc.get_conn()
    user = conn.execute(
        "SELECT id, username, password_hash, role, class_id FROM users WHERE username = ?",
        (username.strip(),),
    ).fetchone()
    if user is None or not security.verify_password(password, user["password_hash"]):
        # 不区分账号是否存在，统一 401；不吊销任何已有会话。
        raise ApiError(401, "INVALID_CREDENTIALS", "账号或密码错误")

    from campusclaw.timeutil import now_utc

    sid = sessions.create_session(
        conn, int(user["id"]), now_utc(), rc.get_settings().session_hours
    )
    class_name = conn.execute(
        "SELECT name FROM classes WHERE id = ?", (int(user["class_id"]),)
    ).fetchone()["name"]
    return jsonify({
        "token": sid,
        "expires_in": rc.get_settings().session_hours * 3600,
        "user": {
            "id": int(user["id"]),
            "username": user["username"],
            "role": user["role"],
            "class_id": int(user["class_id"]),
            "class_name": class_name,
        },
    }), 200


@bp.post("/api/logout")
def api_logout():
    """登出并吊销当前令牌/会话。Bearer 与 Cookie 均可。"""
    user = rc.require_api_auth()
    conn = rc.get_conn()
    sessions.revoke_session(conn, rc.current_sid())
    return jsonify({"ok": True, "username": user["username"]}), 200


@bp.get("/api/me")
def api_me():
    user = rc.require_api_auth()
    return jsonify({
        "id": int(user["user_id"]),
        "username": user["username"],
        "role": user["role"],
        "class_id": int(user["class_id"]),
        "class_name": user["class_name"],
    }), 200
