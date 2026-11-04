"""解题助手数据层：提示词、技能、会话与消息。

与 ``retrieval_db`` 同模式：对现有 SQLite 做增量建表（``CREATE TABLE IF NOT
EXISTS``）与幂等种子，单事务提交；既有账号、材料、知识全文与索引不受影响。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

DEFAULT_PROMPT = (
    "你是学生自学时的解题助手。用简体中文，先确认学生想问的题目，"
    "再结合本班资料给出思路；不要直接替学生写出最终答案。"
)

#: 预置「解题引导」类技能（教师可改可停用）。名称含「解题引导」。
SEED_SKILLS: tuple[dict[str, Any], ...] = (
    {
        "name": "通用解题引导",
        "trigger_text": "",
        "subject": "通用",
        "enabled": 1,
        "description": (
            "先让学生复述题目与已知条件，再指出本题用到的知识点，"
            "给出第一步思路并引用本班材料的标题和位置；不直接给出最终答案。"
        ),
        "source": (
            "名称：通用解题引导\n适用条件：\n工具：knowledge_search\n资料：通用\n启用：是\n\n"
            "先让学生复述题目与已知条件，再指出本题用到的知识点，"
            "给出第一步思路并引用本班材料的标题和位置；不直接给出最终答案。"
        ),
    },
    {
        "name": "方程解题引导",
        "trigger_text": "方程,移项,等式,解方程,一元一次",
        "subject": "数学",
        "enabled": 1,
        "description": (
            "先让学生说出等号两边要保持相等，再示范移项要变号；"
            "引用本班材料中方程相关的标题和位置，不直接给出最终答案。"
        ),
        "source": (
            "名称：方程解题引导\n适用条件：方程,移项,等式,解方程,一元一次\n"
            "工具：knowledge_search\n资料：数学\n启用：是\n\n"
            "先让学生说出等号两边要保持相等，再示范移项要变号；"
            "引用本班材料中方程相关的标题和位置，不直接给出最终答案。"
        ),
    },
)

SKILL_TOOLS = ("knowledge_search",)

#: 第 6 课：技能「工具」栏的 MCP 引用格式唯一定义。
#: 形如「工具名@服务器名」：工具名以小写字母开头、≤32 字符、仅小写字母/数字/下划线；
#: 服务器名额外允许连字符。``mcp_skill`` 复用本定义，不重复声明。
MCP_TOOL_REF_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}@[a-z][a-z0-9-]{0,31}$")

#: 工具栏多项分隔符：半角/全角逗号、分号与竖线。
TOOL_REF_SEPARATORS = ",，;；|"
_TOOL_REF_SPLIT_RE = re.compile("[" + re.escape(TOOL_REF_SEPARATORS) + "]")

MAX_NAME = 32
MAX_TRIGGER = 120
MAX_DESCRIPTION = 2000
MAX_SOURCE = 8000
MAX_PROMPT_BODY = 2000
MAX_QUESTION = 500
MIN_QUESTION = 2
MAX_TITLE = 100


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillFormatError(ValueError):
    """技能文件不合法：消息直接作为 400 文案。"""


def is_mcp_tool_ref(item: str) -> bool:
    """判断一项是否为合法的「工具名@服务器名」MCP 引用（仅查格式）。"""
    return bool(MCP_TOOL_REF_RE.match(item))


def split_tool_refs(text: str) -> list[str]:
    """按 ``,，;；|`` 拆分工具栏文本，去空白、丢空项，保持原顺序。"""
    return [part.strip() for part in _TOOL_REF_SPLIT_RE.split(text) if part.strip()]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """增量建表 + 幂等种子。已播种的提示词/技能不被覆盖。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS class_prompts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id    INTEGER NOT NULL UNIQUE REFERENCES classes(id),
                body        TEXT NOT NULL,
                updated_by  INTEGER REFERENCES users(id),
                updated_at  TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS class_skills (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id     INTEGER NOT NULL REFERENCES classes(id),
                name         TEXT NOT NULL,
                trigger_text TEXT NOT NULL DEFAULT '',
                subject      TEXT NOT NULL DEFAULT '',
                tools_json   TEXT NOT NULL DEFAULT '["knowledge_search"]',
                enabled      INTEGER NOT NULL DEFAULT 1,
                description  TEXT NOT NULL,
                source       TEXT NOT NULL,
                created_by   INTEGER REFERENCES users(id),
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                UNIQUE (class_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                class_id    INTEGER NOT NULL REFERENCES classes(id),
                title       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content         TEXT NOT NULL,
                citations_json  TEXT NOT NULL DEFAULT '[]',
                skill_id        INTEGER,
                skill_name      TEXT NOT NULL DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'ok',
                tool_calls_json TEXT NOT NULL DEFAULT '[]',
                created_at      TEXT NOT NULL
            )
        """)
        _ensure_message_tool_calls_column(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user "
            "ON conversations(user_id, updated_at DESC, id DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation "
            "ON conversation_messages(conversation_id, id)"
        )
        _seed_prompt_and_skills(conn)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _ensure_message_tool_calls_column(conn: sqlite3.Connection) -> None:
    """为既有 ``conversation_messages`` 幂等补列 ``tool_calls_json``。

    新库由 CREATE TABLE 直接含该列；老库在此探测后 ALTER，重复启动不报错。
    调用方负责事务（在 ensure_schema 的 BEGIN/COMMIT 内执行）。
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(conversation_messages)")}
    if "tool_calls_json" not in columns:
        conn.execute(
            "ALTER TABLE conversation_messages ADD COLUMN tool_calls_json TEXT NOT NULL DEFAULT '[]'"
        )


def _seed_prompt_and_skills(conn: sqlite3.Connection) -> None:
    """为没有提示词/技能的班级补种默认值；教师已改过的一律不覆盖。"""
    stamp = utc_now()
    classes = conn.execute("SELECT id FROM classes ORDER BY id").fetchall()
    for row in classes:
        class_id = int(row["id"])
        has_prompt = conn.execute(
            "SELECT 1 FROM class_prompts WHERE class_id = ? LIMIT 1", (class_id,)
        ).fetchone()
        if has_prompt is None:
            conn.execute(
                "INSERT INTO class_prompts(class_id, body, updated_by, updated_at) "
                "VALUES (?, ?, NULL, ?)",
                (class_id, DEFAULT_PROMPT, stamp),
            )
        has_skill = conn.execute(
            "SELECT 1 FROM class_skills WHERE class_id = ? LIMIT 1", (class_id,)
        ).fetchone()
        if has_skill is None:
            for skill in SEED_SKILLS:
                conn.execute(
                    "INSERT INTO class_skills(class_id, name, trigger_text, subject, "
                    "tools_json, enabled, description, source, created_by, created_at, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                    (
                        class_id,
                        skill["name"],
                        skill["trigger_text"],
                        skill["subject"],
                        json.dumps(list(SKILL_TOOLS), ensure_ascii=False),
                        int(skill["enabled"]),
                        skill["description"],
                        skill["source"],
                        stamp,
                        stamp,
                    ),
                )


# ---------------------------------------------------------------------------
# 关键词就绪补建（SQLite 侧，不写 Qdrant）
#
# 第 4 课规约：向量代次由 worker 建立；这里只把「从未被 worker 认领过」的材料
# 补建为关键词就绪代次，使助手开箱即可检索本班资料。之后 worker 认领原任务或
# 教师重建索引时，会以更高代次取代这些切片（_retire_stale 清理旧代次）。
# ---------------------------------------------------------------------------

AUTO_STRATEGY = {"strategy": "auto"}


def _write_keyword_chunks(
    conn: sqlite3.Connection,
    material_id: int,
    class_id: int,
    entry_id: int,
    body_text: str,
) -> int:
    """写一批 ready 关键词切片与 FTS 行；调用方负责事务。"""
    from campusclaw.chunking import split_body
    from campusclaw.retrieval import fts_tokens

    pieces = split_body(body_text, AUTO_STRATEGY)
    if not pieces:
        return 0
    stamp = utc_now()
    strategy_json = json.dumps(AUTO_STRATEGY, ensure_ascii=False, sort_keys=True)
    for chunk in pieces:
        cursor = conn.execute(
            "INSERT INTO knowledge_chunks(knowledge_entry_id, material_id, class_id, "
            "generation, chunk_index, start_offset, end_offset, offset_basis, "
            "strategy_json, chunk_text, index_status, created_at) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'ready', ?)",
            (
                entry_id,
                material_id,
                class_id,
                chunk.index,
                chunk.start,
                chunk.end,
                chunk.offset_basis,
                strategy_json,
                chunk.text,
                stamp,
            ),
        )
        chunk_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO knowledge_chunks_fts(rowid, token_text) VALUES (?, ?)",
            (chunk_id, fts_tokens(chunk.text)),
        )
    conn.execute(
        "INSERT OR REPLACE INTO material_index(material_id, active_generation, status, "
        "strategy_json, last_error, updated_at) VALUES (?, 1, 'ready', ?, NULL, ?)",
        (material_id, strategy_json, stamp),
    )
    # 从未被认领的排队任务标记完成：避免未配置嵌入的 worker 之后把状态改回 failed。
    conn.execute(
        "UPDATE index_jobs SET status = 'done', updated_at = ? "
        "WHERE material_id = ? AND status = 'queued' AND attempts = 0",
        (stamp, material_id),
    )
    return len(pieces)


def backfill_keyword_ready(conn: sqlite3.Connection) -> int:
    """为从未建立切片的 active 材料补建关键词就绪代次，返回材料数。"""
    rows = conn.execute("""
        SELECT m.id, m.class_id, k.id AS entry_id, k.body_text
        FROM materials m
        JOIN knowledge_entries k ON k.material_id = m.id
        WHERE m.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM knowledge_chunks c WHERE c.material_id = m.id)
          AND NOT EXISTS (
              SELECT 1 FROM index_jobs j
              WHERE j.material_id = m.id
                AND j.status IN ('queued', 'running') AND j.attempts > 0)
    """).fetchall()
    count = 0
    for row in rows:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if _write_keyword_chunks(
                conn,
                int(row["id"]),
                int(row["class_id"]),
                int(row["entry_id"]),
                row["body_text"],
            ):
                count += 1
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return count


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------


def get_prompt(conn: sqlite3.Connection, class_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT body, updated_at FROM class_prompts WHERE class_id = ?", (class_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def save_prompt(
    conn: sqlite3.Connection, class_id: int, body: str, updated_by: int
) -> dict[str, Any]:
    stamp = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO class_prompts(class_id, body, updated_by, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(class_id) DO UPDATE SET body = excluded.body, "
            "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (class_id, body, updated_by, stamp),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return {"body": body, "updated_at": stamp}


# ---------------------------------------------------------------------------
# 技能文件解析
# ---------------------------------------------------------------------------


def parse_skill_source(source: str) -> dict[str, Any]:
    """解析技能文件：头部「键：值」+ 一个空行 + 说明。

    非法输入抛 :class:`SkillFormatError`，消息即对外的 400 文案。
    """
    if not isinstance(source, str) or source.strip() == "":
        raise SkillFormatError("技能文件是空的")
    if len(source) > MAX_SOURCE:
        raise SkillFormatError("技能文件过长")

    parts = source.split("\n\n", 1)
    if len(parts) != 2:
        raise SkillFormatError("技能文件需要一个空行，空行下面写技能说明")
    head, description = parts[0], parts[1].strip()

    fields: dict[str, str] = {}
    for line in head.splitlines():
        line = line.strip()
        if not line:
            continue
        if "：" not in line:
            raise SkillFormatError("技能文件需要一个空行，空行下面写技能说明")
        key, value = line.split("：", 1)
        key = key.strip()
        if key not in ("名称", "适用条件", "工具", "资料", "启用"):
            raise SkillFormatError("技能文件字段不正确")
        fields[key] = value.strip()

    for required in ("名称", "适用条件", "工具", "资料", "启用"):
        if required not in fields:
            raise SkillFormatError("技能文件字段不完整")

    name = fields["名称"]
    trigger = fields["适用条件"]
    tools = split_tool_refs(fields["工具"])
    subject = fields["资料"]
    enabled = fields["启用"]

    if not 1 <= len(name) <= MAX_NAME:
        raise SkillFormatError("技能名称长度不正确")
    if len(trigger) > MAX_TRIGGER:
        raise SkillFormatError("适用条件过长")
    if not 1 <= len(description) <= MAX_DESCRIPTION:
        raise SkillFormatError("技能说明长度不正确")
    if not tools or any(
        not (tool == "knowledge_search" or is_mcp_tool_ref(tool)) for tool in tools
    ):
        raise SkillFormatError(
            "技能工具只能是 knowledge_search 或「工具名@服务器名」的 MCP 引用，"
            "例如：工具：knowledge_search, formula_hint@campus-tools"
        )
    if enabled not in ("是", "否"):
        raise SkillFormatError("启用只能写是或否")

    return {
        "name": name,
        "trigger": trigger,
        "tools": tools,
        "subject": subject,
        "enabled": enabled == "是",
        "description": description,
        "source": source,
    }


def _skill_row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "trigger": row["trigger_text"],
        "subject": row["subject"],
        "tools": json.loads(row["tools_json"]),
        "enabled": bool(row["enabled"]),
        "description": row["description"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_skills(conn: sqlite3.Connection, class_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM class_skills WHERE class_id = ? ORDER BY id", (class_id,)
    ).fetchall()
    return [_skill_row_dict(row) for row in rows]


def get_skill(conn: sqlite3.Connection, class_id: int, skill_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM class_skills WHERE class_id = ? AND id = ?", (class_id, skill_id)
    ).fetchone()
    return _skill_row_dict(row) if row is not None else None


def skill_name_taken(
    conn: sqlite3.Connection, class_id: int, name: str, exclude_id: int | None = None
) -> bool:
    if exclude_id is None:
        row = conn.execute(
            "SELECT 1 FROM class_skills WHERE class_id = ? AND name = ? LIMIT 1",
            (class_id, name),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM class_skills WHERE class_id = ? AND name = ? AND id != ? LIMIT 1",
            (class_id, name, exclude_id),
        ).fetchone()
    return row is not None


def create_skill(
    conn: sqlite3.Connection, class_id: int, parsed: dict[str, Any], created_by: int
) -> dict[str, Any]:
    stamp = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO class_skills(class_id, name, trigger_text, subject, tools_json, "
            "enabled, description, source, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                class_id,
                parsed["name"],
                parsed["trigger"],
                parsed["subject"],
                json.dumps(parsed["tools"], ensure_ascii=False),
                int(parsed["enabled"]),
                parsed["description"],
                parsed["source"],
                created_by,
                stamp,
                stamp,
            ),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    skill = get_skill(conn, class_id, int(cursor.lastrowid))
    assert skill is not None
    return skill


def update_skill(
    conn: sqlite3.Connection, class_id: int, skill_id: int, parsed: dict[str, Any]
) -> dict[str, Any] | None:
    stamp = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE class_skills SET name = ?, trigger_text = ?, subject = ?, "
            "tools_json = ?, enabled = ?, description = ?, source = ?, updated_at = ? "
            "WHERE class_id = ? AND id = ?",
            (
                parsed["name"],
                parsed["trigger"],
                parsed["subject"],
                json.dumps(parsed["tools"], ensure_ascii=False),
                int(parsed["enabled"]),
                parsed["description"],
                parsed["source"],
                stamp,
                class_id,
                skill_id,
            ),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    if cursor.rowcount == 0:
        return None
    return get_skill(conn, class_id, skill_id)


def delete_skill(conn: sqlite3.Connection, class_id: int, skill_id: int) -> bool:
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "DELETE FROM class_skills WHERE class_id = ? AND id = ?", (class_id, skill_id)
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return cursor.rowcount > 0


def select_skill(
    conn: sqlite3.Connection, class_id: int, question: str
) -> dict[str, Any] | None:
    """在本班已启用技能中取触发词命中问题的第一条；无触发词视为兜底技能。"""
    rows = conn.execute(
        "SELECT * FROM class_skills WHERE class_id = ? AND enabled = 1 ORDER BY id",
        (class_id,),
    ).fetchall()
    fallback: sqlite3.Row | None = None
    for row in rows:
        triggers = [t.strip() for t in row["trigger_text"].split(",") if t.strip()]
        if not triggers:
            fallback = fallback or row
            continue
        if any(trigger in question for trigger in triggers):
            return _skill_row_dict(row)
    return _skill_row_dict(fallback) if fallback is not None else None


# ---------------------------------------------------------------------------
# 会话与消息
# ---------------------------------------------------------------------------


def create_conversation(
    conn: sqlite3.Connection, user_id: int, class_id: int, title: str
) -> dict[str, Any]:
    stamp = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO conversations(user_id, class_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, class_id, title, stamp, stamp),
        )
        conversation_id = int(cursor.lastrowid)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return get_conversation(conn, user_id, conversation_id) or {
        "id": conversation_id,
        "user_id": user_id,
        "class_id": class_id,
        "title": title,
        "created_at": stamp,
        "updated_at": stamp,
    }


def _conversation_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "class_id": int(row["class_id"]),
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_conversation(
    conn: sqlite3.Connection, user_id: int, conversation_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
        (conversation_id, user_id),
    ).fetchone()
    return _conversation_dict(row) if row is not None else None


def list_conversations(
    conn: sqlite3.Connection, user_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM conversations WHERE user_id = ? "
        "ORDER BY updated_at DESC, id DESC",
        (user_id,),
    ).fetchall()
    return [_conversation_dict(row) for row in rows]


def _message_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {
        "id": int(row["id"]),
        "role": row["role"],
        "content": row["content"],
        "citations": json.loads(row["citations_json"]),
        "skill_name": row["skill_name"],
        "status": row["status"],
        "tool_calls": (
            json.loads(row["tool_calls_json"]) if "tool_calls_json" in keys else []
        ),
        "created_at": row["created_at"],
    }


def list_messages(
    conn: sqlite3.Connection, conversation_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM conversation_messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [_message_dict(row) for row in rows]


def add_message(
    conn: sqlite3.Connection,
    conversation_id: int,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
    skill: dict[str, Any] | None = None,
    status: str = "ok",
    tool_calls: list[dict[str, Any]] | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO conversation_messages(conversation_id, role, content, "
        "citations_json, skill_id, skill_name, status, tool_calls_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            conversation_id,
            role,
            content,
            json.dumps(citations or [], ensure_ascii=False),
            int(skill["id"]) if skill else None,
            skill["name"] if skill else "",
            status,
            json.dumps(tool_calls or [], ensure_ascii=False),
            utc_now(),
        ),
    )
    if role == "user":
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (utc_now(), conversation_id),
        )
    return int(cursor.lastrowid)


def touch_conversation(conn: sqlite3.Connection, conversation_id: int) -> None:
    conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (utc_now(), conversation_id),
    )


def delete_conversation(
    conn: sqlite3.Connection, user_id: int, conversation_id: int
) -> bool:
    """删除本人的会话及其全部消息；他人的会话与不存在返回 False。

    MCP 调用审计要求可追溯，故审计行保留，只把 ``conversation_id`` 置空
    （审计与具体会话脱钩，但仍保留工具引用、状态、用户与时间）。
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return False
        has_audit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mcp_tool_calls'"
        ).fetchone()
        if has_audit is not None:
            conn.execute(
                "UPDATE mcp_tool_calls SET conversation_id = NULL WHERE conversation_id = ?",
                (conversation_id,),
            )
        conn.execute(
            "DELETE FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return True
