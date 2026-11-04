"""MCP 数据层：服务器配置、工具缓存与调用审计。

与 ``tutor_db`` 同模式：对现有 SQLite 做幂等增量建表
（``CREATE TABLE IF NOT EXISTS``，单事务），显式 ``BEGIN IMMEDIATE`` /
``COMMIT`` / ``ROLLBACK``；既有账号、材料、会话等表不受影响。

三张表（见 design.md 3.2）：

* ``mcp_servers``：本班服务器配置（同班同名唯一）；``auth_token`` 仅存服务端。
* ``mcp_tools``：连接时发现的工具缓存，随服务器级联删除（``ON DELETE CASCADE``）。
* ``mcp_tool_calls``：调用审计，只增不改；``server_id`` 无级联——删除已被引用
  的服务器由外键拦下并抛 ``sqlite3.IntegrityError``（视图层转 503）。

班级隔离：所有 CRUD 都带 ``class_id``；对外列表/响应只回 ``has_auth`` 布尔值，
绝不回传令牌原文。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

#: 与 tutor_db.utc_now() 同格式的 UTC ISO 时间戳（自带实现，避免跨模块耦合）。

#: tool_ref / detail 的长度上限（应用层校验/截断，SQLite 不做 VARCHAR 强制）。
MAX_TOOL_REF = 128
MAX_DETAIL = 512


def utc_now() -> str:
    """UTC ISO 8601 时间戳，与 ``tutor_db.utc_now()`` 同格式。"""
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """幂等增量建三张表与审计索引；单事务提交，重复启动不报错。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mcp_servers (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id     INTEGER NOT NULL REFERENCES classes(id),
                name         TEXT NOT NULL,
                base_url     TEXT NOT NULL,
                auth_token   TEXT NOT NULL DEFAULT '',
                connected    INTEGER NOT NULL DEFAULT 0 CHECK (connected IN (0, 1)),
                connected_at TEXT,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                UNIQUE (class_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mcp_tools (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id   INTEGER NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
                tool_name   TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                schema_json TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                UNIQUE (server_id, tool_name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mcp_tool_calls (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id        INTEGER NOT NULL REFERENCES classes(id),
                server_id       INTEGER NOT NULL REFERENCES mcp_servers(id),
                tool_ref        TEXT NOT NULL,
                status          TEXT NOT NULL CHECK (status IN ('ok', 'denied', 'error')),
                detail          TEXT NOT NULL DEFAULT '',
                user_id         INTEGER NOT NULL REFERENCES users(id),
                conversation_id INTEGER REFERENCES conversations(id),
                created_at      TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_class "
            "ON mcp_tool_calls(class_id, created_at DESC, id DESC)"
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# 行字典化：内部访问器返回完整行（含 auth_token，供连接/调用取用）；
# 对外响应经 public_server 去掉令牌、补 has_auth 与 tool_count。
# ---------------------------------------------------------------------------


def _server_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "class_id": int(row["class_id"]),
        "name": row["name"],
        "base_url": row["base_url"],
        "auth_token": row["auth_token"],
        "connected": int(row["connected"]),
        "connected_at": row["connected_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def tool_count(conn: sqlite3.Connection, server_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM mcp_tools WHERE server_id = ?", (server_id,)
    ).fetchone()
    return int(row["n"])


def public_server(conn: sqlite3.Connection, server: dict[str, Any]) -> dict[str, Any]:
    """把完整服务器行转成对外响应：绝不含 auth_token，只回 has_auth。"""
    return {
        "id": server["id"],
        "name": server["name"],
        "base_url": server["base_url"],
        "has_auth": bool(server["auth_token"]),
        "connected": bool(server["connected"]),
        "tool_count": tool_count(conn, server["id"]),
        "connected_at": server["connected_at"],
        "created_at": server["created_at"],
    }


# ---------------------------------------------------------------------------
# 服务器 CRUD
# ---------------------------------------------------------------------------


def list_servers(conn: sqlite3.Connection, class_id: int) -> list[dict[str, Any]]:
    """列出本班服务器（对外形状：has_auth/tool_count，无令牌）。"""
    rows = conn.execute(
        "SELECT * FROM mcp_servers WHERE class_id = ? ORDER BY id", (class_id,)
    ).fetchall()
    return [public_server(conn, _server_row(row)) for row in rows]


def get_server(
    conn: sqlite3.Connection, class_id: int, server_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM mcp_servers WHERE class_id = ? AND id = ?", (class_id, server_id)
    ).fetchone()
    return _server_row(row) if row is not None else None


def get_server_by_name(
    conn: sqlite3.Connection, class_id: int, name: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM mcp_servers WHERE class_id = ? AND name = ?", (class_id, name)
    ).fetchone()
    return _server_row(row) if row is not None else None


def create_server(
    conn: sqlite3.Connection,
    class_id: int,
    name: str,
    base_url: str,
    auth_token: str,
) -> dict[str, Any]:
    """登记服务器：写入后为未连接；同班同名唯一冲突由 UNIQUE 约束拦下。"""
    stamp = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO mcp_servers(class_id, name, base_url, auth_token, "
            "connected, connected_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, NULL, ?, ?)",
            (class_id, name, base_url, auth_token or "", stamp, stamp),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    server = get_server(conn, class_id, int(cursor.lastrowid))
    assert server is not None
    return server


def update_server(
    conn: sqlite3.Connection,
    class_id: int,
    server_id: int,
    name: str | None,
    base_url: str | None,
    auth_token: str | None,
    update_token: bool,
) -> dict[str, Any] | None:
    """修改服务器：任何成功 PUT 都把 connected 置 0 并清空工具缓存（需重连）。

    ``name`` / ``base_url`` 为 None 表示该项不修改；``update_token`` 为 True 时
    用 ``auth_token`` 覆盖令牌，为 False 时保留原令牌（空串/缺省即不修改）。
    """
    existing = get_server(conn, class_id, server_id)
    if existing is None:
        return None
    new_name = name if name is not None else existing["name"]
    new_base_url = base_url if base_url is not None else existing["base_url"]
    new_token = auth_token if update_token else existing["auth_token"]
    stamp = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE mcp_servers SET name = ?, base_url = ?, auth_token = ?, "
            "connected = 0, connected_at = NULL, updated_at = ? "
            "WHERE class_id = ? AND id = ?",
            (new_name, new_base_url, new_token, stamp, class_id, server_id),
        )
        conn.execute("DELETE FROM mcp_tools WHERE server_id = ?", (server_id,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return get_server(conn, class_id, server_id)


def delete_server(conn: sqlite3.Connection, class_id: int, server_id: int) -> bool:
    """删除服务器；工具缓存级联清空。

    若已有调用审计行引用该服务器（``mcp_tool_calls`` 无级联），外键约束会抛
    ``sqlite3.IntegrityError``，由视图层转 503——先保证据，再谈清理。
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "DELETE FROM mcp_servers WHERE class_id = ? AND id = ?",
            (class_id, server_id),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return cursor.rowcount > 0


def set_connected(
    conn: sqlite3.Connection, server_id: int, connected: int, connected_at: str | None
) -> None:
    """只改连接状态（不动工具缓存）；用于连接失败后置回未连接。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE mcp_servers SET connected = ?, connected_at = ?, updated_at = ? "
            "WHERE id = ?",
            (int(connected), connected_at, utc_now(), server_id),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def replace_tool_cache_and_connect(
    conn: sqlite3.Connection, server_id: int, tools: list[dict[str, Any]]
) -> None:
    """覆盖写工具缓存并标记已连接：先删旧缓存再插新清单，最后 connected=1。"""
    stamp = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM mcp_tools WHERE server_id = ?", (server_id,))
        for tool in tools:
            conn.execute(
                "INSERT INTO mcp_tools(server_id, tool_name, description, "
                "schema_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    server_id,
                    tool["name"],
                    tool.get("description", "") or "",
                    json.dumps(tool.get("schema", {}) or {}, ensure_ascii=False),
                    stamp,
                ),
            )
        conn.execute(
            "UPDATE mcp_servers SET connected = 1, connected_at = ?, updated_at = ? "
            "WHERE id = ?",
            (stamp, stamp, server_id),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def mark_disconnected(conn: sqlite3.Connection, server_id: int) -> None:
    """断开：标记未连接并清空该服务器工具缓存。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM mcp_tools WHERE server_id = ?", (server_id,))
        conn.execute(
            "UPDATE mcp_servers SET connected = 0, connected_at = NULL, updated_at = ? "
            "WHERE id = ?",
            (utc_now(), server_id),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# 工具缓存
# ---------------------------------------------------------------------------


def list_tools(conn: sqlite3.Connection, server_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT tool_name, description, schema_json FROM mcp_tools "
        "WHERE server_id = ? ORDER BY id",
        (server_id,),
    ).fetchall()
    return [
        {
            "name": row["tool_name"],
            "description": row["description"],
            "schema": json.loads(row["schema_json"]),
        }
        for row in rows
    ]


def get_tool(
    conn: sqlite3.Connection, server_id: int, tool_name: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT tool_name, description, schema_json FROM mcp_tools "
        "WHERE server_id = ? AND tool_name = ?",
        (server_id, tool_name),
    ).fetchone()
    if row is None:
        return None
    return {
        "name": row["tool_name"],
        "description": row["description"],
        "schema": json.loads(row["schema_json"]),
    }


# ---------------------------------------------------------------------------
# 调用审计（只增不改）
# ---------------------------------------------------------------------------


def record_tool_call(
    conn: sqlite3.Connection,
    class_id: int,
    server_id: int,
    tool_ref: str,
    status: str,
    detail: str,
    user_id: int,
    conversation_id: int | None,
) -> int:
    """写一行调用审计，返回自增 id；detail/tool_ref 在应用层截断到上限。"""
    cursor = conn.execute(
        "INSERT INTO mcp_tool_calls(class_id, server_id, tool_ref, status, detail, "
        "user_id, conversation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            class_id,
            server_id,
            (tool_ref or "")[:MAX_TOOL_REF],
            status,
            (detail or "")[:MAX_DETAIL],
            user_id,
            conversation_id,
            utc_now(),
        ),
    )
    return int(cursor.lastrowid)


def list_tool_calls(
    conn: sqlite3.Connection, class_id: int, limit: int
) -> list[dict[str, Any]]:
    """本班调用审计，只读，按时间倒序；JOIN 出 server_name 与 username。"""
    rows = conn.execute(
        """
        SELECT c.id, c.tool_ref, c.status, c.detail, c.conversation_id, c.created_at,
               s.name AS server_name, u.username
        FROM mcp_tool_calls c
        JOIN mcp_servers s ON s.id = c.server_id
        JOIN users u ON u.id = c.user_id
        WHERE c.class_id = ?
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ?
        """,
        (class_id, int(limit)),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        ref = row["tool_ref"]
        tool_name = ref.split("@", 1)[0] if "@" in ref else ref
        conversation_id = row["conversation_id"]
        result.append(
            {
                "id": int(row["id"]),
                "tool_ref": ref,
                "tool_name": tool_name,
                "server_name": row["server_name"],
                "status": row["status"],
                "detail": row["detail"],
                "username": row["username"],
                "conversation_id": (
                    int(conversation_id) if conversation_id is not None else None
                ),
                "created_at": row["created_at"],
            }
        )
    return result
