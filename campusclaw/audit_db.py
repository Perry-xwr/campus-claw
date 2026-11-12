"""第 9 课 SEC-07：结构化审计事件表。

``mcp_tool_calls`` 记的是「技能调用」，本模块记的是「所有被拒绝的操作」——
401 / 403 / 404 这类被挡下来的尝试，是排查越权与探测的证据，不能只记成功
（课件：失败的尝试也要记）。

字段对齐课件要求的七列，另加 request_id 用于把同一请求的多段日志串起来：

* 操作人 ``actor`` / ``actor_id``
* 操作时间 ``ts``
* 操作类型 ``action``（如 ``api.reject``、``skill.invoke``）
* 操作对象 ``object_type`` + ``object_id``
* 结果状态 ``status``（HTTP 状态码）+ ``code``（业务错误码）
* 技能标识 ``skill_id``
* 用量与耗时 ``duration_ms`` / ``tokens``

写入一律 best-effort：审计失败只记应用日志，绝不影响主请求的结果。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

#: 各字段截断上限：日志内容本身也是数据，超长输入不得撑坏结构。
MAX_ACTOR = 64
MAX_ACTION = 64
MAX_OBJECT_TYPE = 32
MAX_OBJECT_ID = 128
MAX_CODE = 64
MAX_PATH = 256
MAX_REQUEST_ID = 64

#: 需要落审计的拒绝类状态码。
REJECT_STATUSES = frozenset({401, 403, 404})


def utc_now() -> str:
    """UTC ISO 8601 时间戳，与 ``mcp_db.utc_now()`` 同格式。"""
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """幂等建表与索引；重复启动不报错，不影响既有表。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                request_id  TEXT NOT NULL DEFAULT '',
                actor_id    INTEGER,
                actor       TEXT NOT NULL DEFAULT '',
                class_id    INTEGER,
                action      TEXT NOT NULL DEFAULT '',
                object_type TEXT NOT NULL DEFAULT '',
                object_id   TEXT NOT NULL DEFAULT '',
                method      TEXT NOT NULL DEFAULT '',
                path        TEXT NOT NULL DEFAULT '',
                status      INTEGER NOT NULL,
                code        TEXT NOT NULL DEFAULT '',
                skill_id    TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER,
                tokens      INTEGER,
                detail      TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_events_ts "
            "ON audit_events(ts DESC, id DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_events_actor "
            "ON audit_events(actor, ts DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_events_status "
            "ON audit_events(status, ts DESC)"
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def record_event(
    conn: sqlite3.Connection,
    *,
    status: int,
    code: str = "",
    action: str = "api.reject",
    actor: str = "",
    actor_id: int | None = None,
    class_id: int | None = None,
    object_type: str = "",
    object_id: str = "",
    method: str = "",
    path: str = "",
    skill_id: str = "",
    duration_ms: int | None = None,
    tokens: int | None = None,
    request_id: str = "",
    detail: str = "",
) -> int:
    """写一条审计事件，返回自增 id。所有文本字段按上限截断。"""
    cursor = conn.execute(
        "INSERT INTO audit_events(ts, request_id, actor_id, actor, class_id, action, "
        "object_type, object_id, method, path, status, code, skill_id, duration_ms, "
        "tokens, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            utc_now(),
            (request_id or "")[:MAX_REQUEST_ID],
            actor_id,
            (actor or "")[:MAX_ACTOR],
            class_id,
            (action or "api.reject")[:MAX_ACTION],
            (object_type or "")[:MAX_OBJECT_TYPE],
            (object_id or "")[:MAX_OBJECT_ID],
            (method or "")[:16],
            (path or "")[:MAX_PATH],
            int(status),
            (code or "")[:MAX_CODE],
            (skill_id or "")[:MAX_ACTOR],
            int(duration_ms) if duration_ms is not None else None,
            int(tokens) if tokens is not None else None,
            (detail or "")[:512],
        ),
    )
    return int(cursor.lastrowid)


def list_events(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    status: int | None = None,
    actor: str = "",
    skill_id: str = "",
) -> list[dict[str, Any]]:
    """按时间倒序回查审计事件，支持按状态码、操作人、技能标识过滤。"""
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(int(status))
    if actor:
        clauses.append("actor = ?")
        params.append(actor)
    if skill_id:
        clauses.append("skill_id = ?")
        params.append(skill_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(int(limit))
    rows = conn.execute(
        f"""
        SELECT id, ts, request_id, actor_id, actor, class_id, action, object_type,
               object_id, method, path, status, code, skill_id, duration_ms, tokens, detail
        FROM audit_events
        {where}
        ORDER BY ts DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def count_events(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()
    return int(row["n"]) if row is not None else 0
