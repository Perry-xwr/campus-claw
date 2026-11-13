"""班级答疑广场的数据层：建表、领域查询与状态机写入。

与 ``tutor_db`` / ``retrieval_db`` / ``mcp_db`` 同模式：对现有 SQLite 做增量建表
（``CREATE TABLE IF NOT EXISTS``，单事务），不改任何既有表。

设计要点（详见 openspec/changes/add-class-qa-square/design.md）：

- **状态与标记分离**：``status`` 只表达当前所处阶段；``accepted_reply_id`` /
  ``resolved_at`` 表达「是否曾经被解决」。统计一律按字段算，不按状态值算，
  因此「采纳后被关闭」不会丢失解决记录。
- **AI 回答独立成表**：不进 ``qa_replies``，不推进状态、不计入回复数、
  不计入热门排序，从数据层面杜绝污染人工问答语义。
- **班级隔离**：每个查询都把 ``class_id`` 作为条件，跨班与不存在返回同一个 None，
  由视图层统一转成 404。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from campusclaw import db as dbmod
from campusclaw.timeutil import now_iso

#: 标题与正文长度上限（同时用于视图层校验与前端 maxlength）。
MAX_TITLE = 120
MAX_BODY = 5000
MAX_REPLY = 2000
MAX_FAQ_QUESTION = 2000
MAX_FAQ_ANSWER = 5000

#: 分页默认值与上限。
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50

STATUSES = ("OPEN", "ANSWERED", "ACCEPTED", "CLOSED")
OPEN_STATUSES = ("OPEN", "ANSWERED")
SORT_MODES = ("new", "old", "active")

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS qa_questions (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id          INTEGER NOT NULL REFERENCES classes(id),
        author_id         INTEGER NOT NULL REFERENCES users(id),
        title             TEXT NOT NULL,
        body              TEXT NOT NULL,
        status            TEXT NOT NULL DEFAULT 'OPEN'
                          CHECK (status IN ('OPEN','ANSWERED','ACCEPTED','CLOSED')),
        accepted_reply_id INTEGER,
        resolved_at       TEXT,
        closed_at         TEXT,
        handoff_at        TEXT,
        handoff_by        INTEGER REFERENCES users(id),
        created_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL,
        UNIQUE (id, class_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_replies (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL REFERENCES qa_questions(id),
        class_id    INTEGER NOT NULL REFERENCES classes(id),
        author_id   INTEGER NOT NULL REFERENCES users(id),
        body        TEXT NOT NULL,
        is_teacher  INTEGER NOT NULL DEFAULT 0,
        accepted    INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        UNIQUE (id, question_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_ai_answers (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id    INTEGER NOT NULL REFERENCES qa_questions(id),
        class_id       INTEGER NOT NULL REFERENCES classes(id),
        requested_by   INTEGER NOT NULL REFERENCES users(id),
        content        TEXT NOT NULL,
        citations_json TEXT NOT NULL DEFAULT '[]',
        status         TEXT NOT NULL CHECK (status IN ('ok','no_hits','error')),
        retrieval_mode TEXT NOT NULL DEFAULT 'keyword',
        created_at     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_faqs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id      INTEGER NOT NULL REFERENCES classes(id),
        question_id   INTEGER NOT NULL REFERENCES qa_questions(id),
        reply_id      INTEGER REFERENCES qa_replies(id),
        question_text TEXT NOT NULL,
        answer_text   TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'published'
                      CHECK (status IN ('published','revoked')),
        created_by    INTEGER NOT NULL REFERENCES users(id),
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        UNIQUE (question_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS qa_faq_materials (
        class_id    INTEGER PRIMARY KEY REFERENCES classes(id),
        material_id INTEGER NOT NULL REFERENCES materials(id),
        updated_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_qa_questions_class "
    "ON qa_questions(class_id, status, created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_qa_questions_handoff "
    "ON qa_questions(class_id, handoff_at)",
    "CREATE INDEX IF NOT EXISTS idx_qa_replies_question "
    "ON qa_replies(question_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_qa_ai_answers_question "
    "ON qa_ai_answers(question_id, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_qa_faqs_class "
    "ON qa_faqs(class_id, status, updated_at DESC)",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """增量建表。对既有表、账号、材料与索引无破坏，重复启动不报错。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# 行转换
# ---------------------------------------------------------------------------

def _question_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["handoff"] = bool(data.get("handoff_at"))
    data["resolved"] = data.get("accepted_reply_id") is not None
    return data


def _reply_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["is_teacher"] = bool(data.get("is_teacher"))
    data["accepted"] = bool(data.get("accepted"))
    return data


def _ai_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["citations"] = json.loads(data.pop("citations_json") or "[]")
    except (TypeError, ValueError):
        data["citations"] = []
    return data


def _faq_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


# ---------------------------------------------------------------------------
# 问题
# ---------------------------------------------------------------------------

QUESTION_SELECT = """
    SELECT q.*, u.username AS author_name,
           (SELECT COUNT(*) FROM qa_replies r WHERE r.question_id = q.id) AS reply_count
    FROM qa_questions q JOIN users u ON u.id = q.author_id
"""


def create_question(
    conn: sqlite3.Connection, class_id: int, author_id: int, title: str, body: str
) -> dict[str, Any]:
    stamp = now_iso()
    with dbmod.transaction(conn):
        cursor = conn.execute(
            "INSERT INTO qa_questions(class_id, author_id, title, body, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, 'OPEN', ?, ?)",
            (class_id, author_id, title, body, stamp, stamp),
        )
        question_id = int(cursor.lastrowid)
    question = get_question(conn, question_id, class_id)
    assert question is not None
    return question


def get_question(
    conn: sqlite3.Connection, question_id: int, class_id: int
) -> dict[str, Any] | None:
    """按编号取本班问题；跨班与不存在同样返回 None。"""
    row = conn.execute(
        QUESTION_SELECT + " WHERE q.id = ? AND q.class_id = ?",
        (question_id, class_id),
    ).fetchone()
    return _question_dict(row) if row is not None else None


def _status_clause(statuses: list[str] | None) -> tuple[str, list[Any]]:
    if not statuses:
        return "", []
    placeholders = ",".join("?" for _ in statuses)
    return f" AND q.status IN ({placeholders})", list(statuses)


def list_questions(
    conn: sqlite3.Connection,
    class_id: int,
    *,
    statuses: list[str] | None = None,
    sort: str = "new",
    page: int = 1,
    size: int = DEFAULT_PAGE_SIZE,
    handoff_only: bool = False,
    unresolved_only: bool = False,
) -> dict[str, Any]:
    """本班问题列表，返回 ``{items, total, page, size}``。

    ``sort=active`` 按回复数倒序（热门优先），其余按发布时间。
    ``handoff_only`` 与 ``unresolved_only`` 用于教师待办。
    """
    where = ["q.class_id = ?"]
    params: list[Any] = [class_id]
    clause, extra = _status_clause(statuses)
    if clause:
        where.append(clause.removeprefix(" AND "))
        params.extend(extra)
    if handoff_only:
        where.append("q.handoff_at IS NOT NULL")
    if unresolved_only:
        where.append("q.status IN ('OPEN','ANSWERED')")
    where_sql = " AND ".join(where)

    order_sql = {
        "new": "q.created_at DESC, q.id DESC",
        "old": "q.created_at ASC, q.id ASC",
        "active": "reply_count DESC, q.created_at DESC, q.id DESC",
    }.get(sort, "q.created_at DESC, q.id DESC")
    if handoff_only:
        order_sql = "q.handoff_at ASC, q.id ASC"

    total = int(
        conn.execute(
            "SELECT COUNT(*) FROM qa_questions q WHERE " + where_sql, params
        ).fetchone()[0]
    )
    offset = (page - 1) * size
    rows = conn.execute(
        QUESTION_SELECT + f" WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        [*params, size, offset],
    ).fetchall()
    return {
        "items": [_question_dict(row) for row in rows],
        "total": total,
        "page": page,
        "size": size,
    }


def list_replies(conn: sqlite3.Connection, question_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT r.*, u.username AS author_name, u.role AS author_role "
        "FROM qa_replies r JOIN users u ON u.id = r.author_id "
        "WHERE r.question_id = ? ORDER BY r.id ASC",
        (question_id,),
    ).fetchall()
    return [_reply_dict(row) for row in rows]


# ---------------------------------------------------------------------------
# 回复与状态推进
# ---------------------------------------------------------------------------

class QuestionClosed(RuntimeError):
    """问题已关闭，不允许继续回复或转人工。"""


class ReplyNotFound(RuntimeError):
    """回复不存在，或不属于当前问题。"""


def add_reply(
    conn: sqlite3.Connection,
    question_id: int,
    class_id: int,
    author_id: int,
    body: str,
    is_teacher: bool,
) -> dict[str, Any]:
    """新增人工回复；``OPEN`` / ``ANSWERED`` 一律推进到 ``ANSWERED``。

    已关闭抛 :class:`QuestionClosed`，由视图层转 409。
    """
    stamp = now_iso()
    with dbmod.transaction(conn):
        row = conn.execute(
            "SELECT status FROM qa_questions WHERE id = ? AND class_id = ?",
            (question_id, class_id),
        ).fetchone()
        if row is None:
            raise ReplyNotFound("question not found")
        if row["status"] == "CLOSED":
            raise QuestionClosed("question is closed")
        cursor = conn.execute(
            "INSERT INTO qa_replies(question_id, class_id, author_id, body, "
            "is_teacher, accepted, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (question_id, class_id, author_id, body, int(is_teacher), stamp),
        )
        reply_id = int(cursor.lastrowid)
        # 采纳后追加回复不改变 ACCEPTED，其余状态一律视为已有回复。
        conn.execute(
            "UPDATE qa_questions SET status = CASE WHEN status = 'ACCEPTED' "
            "THEN 'ACCEPTED' ELSE 'ANSWERED' END, updated_at = ? "
            "WHERE id = ? AND class_id = ?",
            (stamp, question_id, class_id),
        )
    reply = conn.execute(
        "SELECT r.*, u.username AS author_name, u.role AS author_role "
        "FROM qa_replies r JOIN users u ON u.id = r.author_id WHERE r.id = ?",
        (reply_id,),
    ).fetchone()
    assert reply is not None
    return _reply_dict(reply)


def mark_handoff(
    conn: sqlite3.Connection, question_id: int, class_id: int, user_id: int
) -> dict[str, Any] | None:
    """标记转人工；幂等，重复调用不覆盖首次时间与操作者。"""
    stamp = now_iso()
    with dbmod.transaction(conn):
        row = conn.execute(
            "SELECT status, handoff_at FROM qa_questions WHERE id = ? AND class_id = ?",
            (question_id, class_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "CLOSED":
            raise QuestionClosed("question is closed")
        if row["handoff_at"] is None:
            conn.execute(
                "UPDATE qa_questions SET handoff_at = ?, handoff_by = ?, updated_at = ? "
                "WHERE id = ? AND class_id = ?",
                (stamp, user_id, stamp, question_id, class_id),
            )
    return get_question(conn, question_id, class_id)


def accept_reply(
    conn: sqlite3.Connection, question_id: int, class_id: int, reply_id: int
) -> dict[str, Any] | None:
    """采纳一条属于本问题的回复。

    回复不属于该问题（含指向他班问题）抛 :class:`ReplyNotFound`，视图层转 400。
    采纳后即使问题已关闭也允许（教师可补采纳），但不会把 CLOSED 改回 ACCEPTED。
    """
    stamp = now_iso()
    with dbmod.transaction(conn):
        question = conn.execute(
            "SELECT status FROM qa_questions WHERE id = ? AND class_id = ?",
            (question_id, class_id),
        ).fetchone()
        if question is None:
            return None
        reply = conn.execute(
            "SELECT id FROM qa_replies WHERE id = ? AND question_id = ? AND class_id = ?",
            (reply_id, question_id, class_id),
        ).fetchone()
        if reply is None:
            raise ReplyNotFound("reply not in question")
        # 先清旧采纳，再设新采纳，保证同问题最多一条 accepted=1。
        conn.execute(
            "UPDATE qa_replies SET accepted = 0 WHERE question_id = ? AND accepted = 1",
            (question_id,),
        )
        conn.execute("UPDATE qa_replies SET accepted = 1 WHERE id = ?", (reply_id,))
        next_status = "CLOSED" if question["status"] == "CLOSED" else "ACCEPTED"
        conn.execute(
            "UPDATE qa_questions SET status = ?, accepted_reply_id = ?, "
            "resolved_at = COALESCE(resolved_at, ?), updated_at = ? "
            "WHERE id = ? AND class_id = ?",
            (next_status, reply_id, stamp, stamp, question_id, class_id),
        )
    return get_question(conn, question_id, class_id)


class NotAccepted(RuntimeError):
    """当前问题尚未采纳任何回答。"""


def unaccept(conn: sqlite3.Connection, question_id: int, class_id: int) -> dict[str, Any] | None:
    """取消采纳：清空采纳标记，状态回到 ANSWERED（有回复）或 OPEN。"""
    stamp = now_iso()
    with dbmod.transaction(conn):
        row = conn.execute(
            "SELECT status, accepted_reply_id FROM qa_questions "
            "WHERE id = ? AND class_id = ?",
            (question_id, class_id),
        ).fetchone()
        if row is None:
            return None
        if row["accepted_reply_id"] is None:
            raise NotAccepted("question has no accepted reply")
        conn.execute(
            "UPDATE qa_replies SET accepted = 0 WHERE question_id = ? AND accepted = 1",
            (question_id,),
        )
        has_reply = conn.execute(
            "SELECT 1 FROM qa_replies WHERE question_id = ? LIMIT 1", (question_id,)
        ).fetchone()
        next_status = "ANSWERED" if has_reply else "OPEN"
        if row["status"] == "CLOSED":
            next_status = "CLOSED"
        conn.execute(
            "UPDATE qa_questions SET status = ?, accepted_reply_id = NULL, "
            "resolved_at = NULL, updated_at = ? WHERE id = ? AND class_id = ?",
            (next_status, stamp, question_id, class_id),
        )
    return get_question(conn, question_id, class_id)


class AlreadyClosed(RuntimeError):
    """问题已关闭。"""


class NotClosed(RuntimeError):
    """问题未关闭。"""


def close_question(
    conn: sqlite3.Connection, question_id: int, class_id: int
) -> dict[str, Any] | None:
    """关闭问题；``accepted_reply_id`` 与 ``resolved_at`` 保留，统计不受影响。"""
    stamp = now_iso()
    with dbmod.transaction(conn):
        row = conn.execute(
            "SELECT status FROM qa_questions WHERE id = ? AND class_id = ?",
            (question_id, class_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "CLOSED":
            raise AlreadyClosed("question already closed")
        conn.execute(
            "UPDATE qa_questions SET status = 'CLOSED', closed_at = ?, updated_at = ? "
            "WHERE id = ? AND class_id = ?",
            (stamp, stamp, question_id, class_id),
        )
    return get_question(conn, question_id, class_id)


def reopen_question(
    conn: sqlite3.Connection, question_id: int, class_id: int
) -> dict[str, Any] | None:
    """重新打开；回到 ANSWERED（有回复）或 OPEN，采纳记录保留。"""
    stamp = now_iso()
    with dbmod.transaction(conn):
        row = conn.execute(
            "SELECT status, accepted_reply_id FROM qa_questions "
            "WHERE id = ? AND class_id = ?",
            (question_id, class_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] != "CLOSED":
            raise NotClosed("question is not closed")
        has_reply = conn.execute(
            "SELECT 1 FROM qa_replies WHERE question_id = ? LIMIT 1", (question_id,)
        ).fetchone()
        if row["accepted_reply_id"] is not None:
            next_status = "ACCEPTED"
        else:
            next_status = "ANSWERED" if has_reply else "OPEN"
        conn.execute(
            "UPDATE qa_questions SET status = ?, closed_at = NULL, updated_at = ? "
            "WHERE id = ? AND class_id = ?",
            (next_status, stamp, question_id, class_id),
        )
    return get_question(conn, question_id, class_id)


# ---------------------------------------------------------------------------
# AI 辅助回答
# ---------------------------------------------------------------------------

def add_ai_answer(
    conn: sqlite3.Connection,
    question_id: int,
    class_id: int,
    requested_by: int,
    content: str,
    citations: list[dict],
    status: str,
    retrieval_mode: str,
) -> int:
    with dbmod.transaction(conn):
        cursor = conn.execute(
            "INSERT INTO qa_ai_answers(question_id, class_id, requested_by, content, "
            "citations_json, status, retrieval_mode, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                question_id,
                class_id,
                requested_by,
                content,
                json.dumps(citations, ensure_ascii=False),
                status,
                retrieval_mode,
                now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def latest_ai_answer(
    conn: sqlite3.Connection, question_id: int, class_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM qa_ai_answers WHERE question_id = ? AND class_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (question_id, class_id),
    ).fetchone()
    return _ai_dict(row) if row is not None else None


def ai_answer_count(conn: sqlite3.Connection, question_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM qa_ai_answers WHERE question_id = ?", (question_id,)
        ).fetchone()[0]
    )


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------

FAQ_SELECT = "SELECT f.*, q.status AS question_status FROM qa_faqs f JOIN qa_questions q ON q.id = f.question_id"


def class_published_faqs(conn: sqlite3.Connection, class_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        FAQ_SELECT + " WHERE f.class_id = ? AND f.status = 'published' ORDER BY f.updated_at DESC, f.id DESC",
        (class_id,),
    ).fetchall()
    return [_faq_dict(row) for row in rows]


def list_faqs(
    conn: sqlite3.Connection, class_id: int, include_revoked: bool = False
) -> list[dict[str, Any]]:
    sql = FAQ_SELECT + " WHERE f.class_id = ?"
    params: list[Any] = [class_id]
    if not include_revoked:
        sql += " AND f.status = 'published'"
    sql += " ORDER BY f.updated_at DESC, f.id DESC"
    rows = conn.execute(sql, params).fetchall()
    return [_faq_dict(row) for row in rows]


def get_faq(
    conn: sqlite3.Connection, faq_id: int, class_id: int, include_revoked: bool = False
) -> dict[str, Any] | None:
    sql = FAQ_SELECT + " WHERE f.id = ? AND f.class_id = ?"
    if not include_revoked:
        sql += " AND f.status = 'published'"
    row = conn.execute(sql, (faq_id, class_id)).fetchone()
    return _faq_dict(row) if row is not None else None


def faq_for_question(
    conn: sqlite3.Connection, question_id: int, class_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        FAQ_SELECT + " WHERE f.question_id = ? AND f.class_id = ?",
        (question_id, class_id),
    ).fetchone()
    return _faq_dict(row) if row is not None else None


class FaqExists(RuntimeError):
    """该问题已有 FAQ。"""


class FaqRevoked(RuntimeError):
    """该 FAQ 已撤销。"""


class FaqPublished(RuntimeError):
    """该 FAQ 已发布。"""


def create_faq(
    conn: sqlite3.Connection,
    class_id: int,
    question_id: int,
    reply_id: int | None,
    question_text: str,
    answer_text: str,
    created_by: int,
) -> int:
    stamp = now_iso()
    with dbmod.transaction(conn):
        existing = conn.execute(
            "SELECT id FROM qa_faqs WHERE question_id = ?", (question_id,)
        ).fetchone()
        if existing is not None:
            raise FaqExists("faq already exists for this question")
        cursor = conn.execute(
            "INSERT INTO qa_faqs(class_id, question_id, reply_id, question_text, "
            "answer_text, status, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'published', ?, ?, ?)",
            (
                class_id,
                question_id,
                reply_id,
                question_text,
                answer_text,
                created_by,
                stamp,
                stamp,
            ),
        )
        return int(cursor.lastrowid)


def update_faq(
    conn: sqlite3.Connection,
    faq_id: int,
    class_id: int,
    question_text: str,
    answer_text: str,
) -> dict[str, Any] | None:
    stamp = now_iso()
    with dbmod.transaction(conn):
        row = conn.execute(
            "SELECT status FROM qa_faqs WHERE id = ? AND class_id = ?",
            (faq_id, class_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE qa_faqs SET question_text = ?, answer_text = ?, updated_at = ? "
            "WHERE id = ? AND class_id = ?",
            (question_text, answer_text, stamp, faq_id, class_id),
        )
    return get_faq(conn, faq_id, class_id, include_revoked=True)


def revoke_faq(conn: sqlite3.Connection, faq_id: int, class_id: int) -> bool | None:
    stamp = now_iso()
    with dbmod.transaction(conn):
        row = conn.execute(
            "SELECT status FROM qa_faqs WHERE id = ? AND class_id = ?",
            (faq_id, class_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "revoked":
            raise FaqRevoked("faq already revoked")
        conn.execute(
            "UPDATE qa_faqs SET status = 'revoked', updated_at = ? "
            "WHERE id = ? AND class_id = ?",
            (stamp, faq_id, class_id),
        )
    return True


def republish_faq(conn: sqlite3.Connection, faq_id: int, class_id: int) -> bool | None:
    stamp = now_iso()
    with dbmod.transaction(conn):
        row = conn.execute(
            "SELECT status FROM qa_faqs WHERE id = ? AND class_id = ?",
            (faq_id, class_id),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "published":
            raise FaqPublished("faq already published")
        conn.execute(
            "UPDATE qa_faqs SET status = 'published', updated_at = ? "
            "WHERE id = ? AND class_id = ?",
            (stamp, faq_id, class_id),
        )
    return True


def _faq_question_text(title: str, body: str) -> str:
    """拼 FAQ 的问题正文，并去掉标题与正文的重复。

    提问页的标题与正文是两个输入框，使用者常把同一句话在两处各写一遍
    （实测数据里就有一条：正文开头与标题逐字相同）。原样拼起来之后，
    发布的 FAQ 会变成「标题一遍、正文又一遍」，读起来像系统出了错——
    而这只是把两个字段直接相加的结果。
    """
    title = (title or "").strip()
    body = (body or "").strip()
    if not body:
        return title
    if title and body.startswith(title):
        body = body[len(title):].lstrip(" \t\r\n。.，,：:；;、")
    if not body or body == title:
        return title
    return f"{title}\n\n{body}"


def faq_draft(
    conn: sqlite3.Connection, question_id: int, class_id: int
) -> dict[str, Any] | None:
    """由已采纳问题生成草稿（不落库）；未采纳返回 None，由视图层转 400。"""
    question = get_question(conn, question_id, class_id)
    if question is None:
        return None
    if question["accepted_reply_id"] is None:
        return None
    reply = conn.execute(
        "SELECT * FROM qa_replies WHERE id = ? AND question_id = ?",
        (question["accepted_reply_id"], question_id),
    ).fetchone()
    if reply is None:
        return None
    return {
        "question_id": question_id,
        "reply_id": int(reply["id"]),
        "title": question["title"],
        "question_text": _faq_question_text(question["title"], question["body"]),
        "answer_text": reply["body"],
        "existing_faq": faq_for_question(conn, question_id, class_id),
    }


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

def stats(conn: sqlite3.Connection, class_id: int, *, top_limit: int = 5) -> dict[str, Any]:
    """本班统计。三项分类按字段计算，保证 ``pending + resolved + closed_unresolved == total``。"""
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status IN ('OPEN','ANSWERED') THEN 1 ELSE 0 END) AS pending, "
        "SUM(CASE WHEN accepted_reply_id IS NOT NULL THEN 1 ELSE 0 END) AS resolved, "
        "SUM(CASE WHEN status = 'CLOSED' AND accepted_reply_id IS NULL "
        "THEN 1 ELSE 0 END) AS closed_unresolved, "
        "SUM(CASE WHEN handoff_at IS NOT NULL AND status IN ('OPEN','ANSWERED') "
        "THEN 1 ELSE 0 END) AS handoff_pending "
        "FROM qa_questions WHERE class_id = ?",
        (class_id,),
    ).fetchone()
    total = int(row["total"] or 0)
    pending = int(row["pending"] or 0)
    resolved = int(row["resolved"] or 0)
    closed_unresolved = int(row["closed_unresolved"] or 0)
    handoff_pending = int(row["handoff_pending"] or 0)

    top_rows = conn.execute(
        "SELECT q.id, q.title, q.status, COUNT(r.id) AS reply_count "
        "FROM qa_questions q LEFT JOIN qa_replies r ON r.question_id = q.id "
        "WHERE q.class_id = ? GROUP BY q.id "
        "HAVING reply_count > 0 ORDER BY reply_count DESC, q.id DESC LIMIT ?",
        (class_id, top_limit),
    ).fetchall()

    # 最近 7 天（含今天）每日新增问题数，按本地日期归档。
    trend_rows = conn.execute(
        "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n FROM qa_questions "
        "WHERE class_id = ? GROUP BY day ORDER BY day DESC LIMIT 7",
        (class_id,),
    ).fetchall()
    trend = [{"day": r["day"], "count": int(r["n"])} for r in reversed(trend_rows)]

    faq_total = int(
        conn.execute(
            "SELECT COUNT(*) FROM qa_faqs WHERE class_id = ? AND status = 'published'",
            (class_id,),
        ).fetchone()[0]
    )
    return {
        "pending": pending,
        "resolved": resolved,
        "closed_unresolved": closed_unresolved,
        "handoff_pending": handoff_pending,
        "total": total,
        "faq_total": faq_total,
        "top_questions": [
            {
                "id": int(r["id"]),
                "title": r["title"],
                "status": r["status"],
                "reply_count": int(r["reply_count"]),
            }
            for r in top_rows
        ],
        "trend": trend,
    }


# ---------------------------------------------------------------------------
# FAQ 汇总材料映射
# ---------------------------------------------------------------------------

def faq_material_id(conn: sqlite3.Connection, class_id: int) -> int | None:
    row = conn.execute(
        "SELECT material_id FROM qa_faq_materials WHERE class_id = ?", (class_id,)
    ).fetchone()
    return int(row["material_id"]) if row is not None else None


def set_faq_material_id(conn: sqlite3.Connection, class_id: int, material_id: int) -> None:
    with dbmod.transaction(conn):
        conn.execute(
            "INSERT INTO qa_faq_materials(class_id, material_id, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(class_id) DO UPDATE SET "
            "material_id = excluded.material_id, updated_at = excluded.updated_at",
            (class_id, material_id, now_iso()),
        )
