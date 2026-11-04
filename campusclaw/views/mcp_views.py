"""MCP 管理接口：本班服务器登记/改/删/连接/断开、工具清单与调用审计。

蓝图 ``mcp_api``，8 个接口全部挂在「登录即可 + 仅教师」之后：

* 读接口 = ``require_api_auth`` + 角色必须 teacher（非 teacher 403）；
* 写接口 = ``require_write``（认证 → 教师 → CSRF；Bearer 免 CSRF）。

班级一律取自登录会话，不从请求读；跨班与不存在统一 404，同码同文。
响应里的服务器项只回 ``has_auth`` 与 ``tool_count``，绝不回传令牌原文。
"""

from __future__ import annotations

import re
import sqlite3

from flask import Blueprint, jsonify, request

from campusclaw import mcp_client, mcp_db
from campusclaw import request_context as rc
from campusclaw.errors import ApiError, MESSAGES

bp = Blueprint("mcp_api", __name__)

#: 服务器名称规则：小写字母开头，仅小写字母/数字/连字符，总长 1～64。
SERVER_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

#: 地址与令牌长度上限。
MAX_BASE_URL = 512
MAX_AUTH_TOKEN = 512

#: 审计查询条数：缺省 50、上限 100。
DEFAULT_CALL_LIMIT = 50
MAX_CALL_LIMIT = 100


def _parse_id(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, "MCP_ID_INVALID", MESSAGES["MCP_ID_INVALID"]) from None
    if value < 1:
        raise ApiError(400, "MCP_ID_INVALID", MESSAGES["MCP_ID_INVALID"])
    return value


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "MCP_INVALID_INPUT", MESSAGES["MCP_INVALID_INPUT"])
    return body


def _require_teacher_read() -> dict:
    """读接口权限链：认证 → 仅教师。"""
    user = rc.require_api_auth()
    if user["role"] != "teacher":
        raise ApiError(403, "ROLE_FORBIDDEN", MESSAGES["ROLE_FORBIDDEN"])
    return user


def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not SERVER_NAME_RE.match(name):
        raise ApiError(
            400,
            "MCP_INVALID_INPUT",
            "MCP 服务器名称须为 1～64 个字符，小写字母开头，仅含小写字母、数字或连字符",
        )
    return name


def _validate_base_url(base_url: object) -> str:
    if not isinstance(base_url, str):
        raise ApiError(400, "MCP_INVALID_INPUT", "MCP 服务器地址不能为空")
    value = base_url.strip()
    if not 1 <= len(value) <= MAX_BASE_URL or not (
        value.startswith("http://") or value.startswith("https://")
    ):
        raise ApiError(
            400,
            "MCP_INVALID_INPUT",
            "MCP 服务器地址须以 http:// 或 https:// 开头且不超过 512 字符",
        )
    # 存储时裁剪尾部斜杠；调用时拼 /mcp。
    return value.rstrip("/")


def _validate_token(token: object) -> str:
    if not isinstance(token, str):
        raise ApiError(400, "MCP_INVALID_INPUT", "MCP 服务器令牌格式不正确")
    if len(token) > MAX_AUTH_TOKEN:
        raise ApiError(400, "MCP_INVALID_INPUT", "MCP 服务器令牌过长")
    return token


@bp.get("/api/mcp/servers")
def list_servers_api():
    """MCP-001：列出本班服务器（含工具数量与连接状态）。"""
    user = _require_teacher_read()
    servers = mcp_db.list_servers(rc.get_conn(), int(user["class_id"]))
    return jsonify({"servers": servers}), 200


@bp.post("/api/mcp/servers")
def create_server_api():
    """MCP-002：登记服务器（名称、Base URL、令牌）；登记后为未连接。"""
    user = rc.require_write()
    body = _json_body()
    rc.reject_identity_fields(body)
    name = _validate_name(body.get("name"))
    base_url = _validate_base_url(body.get("base_url"))
    raw_token = body.get("auth_token")
    auth_token = "" if raw_token is None else _validate_token(raw_token)

    conn = rc.get_conn()
    class_id = int(user["class_id"])
    if mcp_db.get_server_by_name(conn, class_id, name) is not None:
        raise ApiError(400, "MCP_NAME_EXISTS", MESSAGES["MCP_NAME_EXISTS"])
    try:
        server = mcp_db.create_server(conn, class_id, name, base_url, auth_token)
    except sqlite3.IntegrityError:
        # 同班同名唯一冲突（含校验与插入之间的竞态）。
        raise ApiError(400, "MCP_NAME_EXISTS", MESSAGES["MCP_NAME_EXISTS"]) from None
    return jsonify({"server": mcp_db.public_server(conn, server)}), 201


@bp.put("/api/mcp/servers/<server_id>")
def update_server_api(server_id: str):
    """MCP-003：修改服务器；任何成功 PUT 都置回未连接并清空工具缓存。"""
    user = rc.require_write()
    server_id_int = _parse_id(server_id)
    body = _json_body()
    rc.reject_identity_fields(body)

    name = body.get("name")
    base_url = body.get("base_url")
    if name is None and base_url is None:
        raise ApiError(
            400, "MCP_INVALID_INPUT", "修改 MCP 服务器至少需要提供名称或地址之一"
        )
    new_name = _validate_name(name) if name is not None else None
    new_base_url = _validate_base_url(base_url) if base_url is not None else None

    # 令牌：空串或缺省 = 不修改；非空 = 覆盖。
    raw_token = body.get("auth_token")
    update_token = False
    token_value: str | None = None
    if raw_token is not None:
        token_value = _validate_token(raw_token)
        if token_value != "":
            update_token = True

    conn = rc.get_conn()
    class_id = int(user["class_id"])
    existing = mcp_db.get_server(conn, class_id, server_id_int)
    if existing is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    if new_name is not None and new_name != existing["name"]:
        if mcp_db.get_server_by_name(conn, class_id, new_name) is not None:
            raise ApiError(400, "MCP_NAME_EXISTS", MESSAGES["MCP_NAME_EXISTS"])
    try:
        updated = mcp_db.update_server(
            conn, class_id, server_id_int, new_name, new_base_url, token_value, update_token
        )
    except sqlite3.IntegrityError:
        raise ApiError(400, "MCP_NAME_EXISTS", MESSAGES["MCP_NAME_EXISTS"]) from None
    if updated is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    return jsonify({"server": mcp_db.public_server(conn, updated)}), 200


@bp.delete("/api/mcp/servers/<server_id>")
def delete_server_api(server_id: str):
    """MCP-004：删除服务器；工具缓存级联清空，有审计则被外键拦下返回 503。"""
    user = rc.require_write()
    server_id_int = _parse_id(server_id)
    conn = rc.get_conn()
    class_id = int(user["class_id"])
    try:
        deleted = mcp_db.delete_server(conn, class_id, server_id_int)
    except sqlite3.IntegrityError:
        # 已有调用审计记录：先保证据，再谈清理。
        raise ApiError(503, "MCP_SERVER_BUSY", MESSAGES["MCP_SERVER_BUSY"]) from None
    if not deleted:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    return "", 204


@bp.post("/api/mcp/servers/<server_id>/connect")
def connect_server_api(server_id: str):
    """MCP-005：连接并发现；覆盖写工具缓存并标记已连接；失败置回未连接返回 502。"""
    user = rc.require_write()
    server_id_int = _parse_id(server_id)
    conn = rc.get_conn()
    class_id = int(user["class_id"])
    server = mcp_db.get_server(conn, class_id, server_id_int)
    if server is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    try:
        discovered = mcp_client.discover_tools(server["base_url"], server["auth_token"])
    except mcp_client.McpCallError as exc:
        # 握手或发现任一步失败：只置回未连接，不动旧缓存。
        mcp_db.set_connected(conn, server_id_int, 0, None)
        raise ApiError(502, "MCP_CONNECT_FAILED", str(exc)) from None
    try:
        mcp_db.replace_tool_cache_and_connect(conn, server_id_int, discovered)
    except sqlite3.Error:
        raise ApiError(503, "MCP_UNAVAILABLE", MESSAGES["MCP_UNAVAILABLE"]) from None
    updated = mcp_db.get_server(conn, class_id, server_id_int)
    if updated is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    tools = [{"name": item["name"], "description": item["description"]} for item in discovered]
    return jsonify({"server": mcp_db.public_server(conn, updated), "tools": tools}), 200


@bp.post("/api/mcp/servers/<server_id>/disconnect")
def disconnect_server_api(server_id: str):
    """MCP-006：断开；标记未连接并清空该服务器工具缓存。"""
    user = rc.require_write()
    server_id_int = _parse_id(server_id)
    conn = rc.get_conn()
    class_id = int(user["class_id"])
    server = mcp_db.get_server(conn, class_id, server_id_int)
    if server is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    mcp_db.mark_disconnected(conn, server_id_int)
    updated = mcp_db.get_server(conn, class_id, server_id_int)
    if updated is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    return jsonify({"server": mcp_db.public_server(conn, updated)}), 200


@bp.get("/api/mcp/servers/<server_id>/tools")
def list_tools_api(server_id: str):
    """MCP-007：查看该服务器已发现的工具清单。"""
    user = _require_teacher_read()
    server_id_int = _parse_id(server_id)
    conn = rc.get_conn()
    class_id = int(user["class_id"])
    server = mcp_db.get_server(conn, class_id, server_id_int)
    if server is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    tools = mcp_db.list_tools(conn, server_id_int)
    return jsonify({"tools": tools}), 200


@bp.get("/api/mcp/tool-calls")
def list_tool_calls_api():
    """MCP-008：本班最近调用审计，只读，按时间倒序，默认 50、上限 100。"""
    user = _require_teacher_read()
    raw_limit = request.args.get("limit", str(DEFAULT_CALL_LIMIT))
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise ApiError(
            400, "MCP_INVALID_INPUT", "审计条数 limit 须为 1～100 的整数"
        ) from None
    if limit < 1:
        raise ApiError(400, "MCP_INVALID_INPUT", "审计条数 limit 须为 1～100 的整数")
    limit = min(limit, MAX_CALL_LIMIT)
    calls = mcp_db.list_tool_calls(rc.get_conn(), int(user["class_id"]), limit)
    return jsonify({"calls": calls}), 200
