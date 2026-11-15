"""Additive retrieval schema and durable indexing queue for the existing SQLite DB."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

AUTO_STRATEGY = {"strategy": "auto"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Migrate in place. Existing users, materials and knowledge rows are untouched."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS material_index (
                material_id INTEGER PRIMARY KEY REFERENCES materials(id),
                active_generation INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','ready','failed')),
                strategy_json TEXT NOT NULL DEFAULT '{"strategy":"auto"}',
                last_error TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_entry_id INTEGER NOT NULL,
                material_id INTEGER NOT NULL REFERENCES materials(id),
                class_id INTEGER NOT NULL REFERENCES classes(id),
                generation INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                offset_basis TEXT NOT NULL CHECK (offset_basis IN ('original','processed')),
                strategy_json TEXT NOT NULL DEFAULT '{"strategy":"auto"}',
                chunk_text TEXT NOT NULL,
                index_status TEXT NOT NULL CHECK (index_status IN ('pending','ready','failed')),
                created_at TEXT NOT NULL,
                UNIQUE(material_id,generation,chunk_index)
            )
        """)
        if "strategy_json" not in {row["name"] for row in conn.execute("PRAGMA table_info(knowledge_chunks)")}:
            conn.execute("ALTER TABLE knowledge_chunks ADD COLUMN strategy_json TEXT NOT NULL DEFAULT '{\"strategy\":\"auto\"}'")
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
            USING fts5(token_text, tokenize='unicode61')
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS index_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL REFERENCES materials(id),
                strategy_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_material_gen ON knowledge_chunks(material_id,generation)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_class_ready ON knowledge_chunks(class_id,index_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_index_jobs_status ON index_jobs(status,id)")
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS queue_new_knowledge_entry
            AFTER INSERT ON knowledge_entries
            BEGIN
                INSERT OR IGNORE INTO material_index(material_id,status,updated_at)
                VALUES (NEW.material_id,'pending',NEW.created_at);
                INSERT INTO index_jobs(material_id,strategy_json,status,created_at,updated_at)
                VALUES (NEW.material_id,'{"strategy":"auto"}','queued',NEW.created_at,NEW.created_at);
            END
        """)
        # Enqueue the preexisting A/B samples and any other material once only.
        stamp = utc_now()
        conn.execute("""
            INSERT OR IGNORE INTO material_index(material_id,status,updated_at)
            SELECT m.id,'pending',? FROM materials m
            JOIN knowledge_entries k ON k.material_id=m.id
            WHERE m.status='active'
        """, (stamp,))
        conn.execute("""
            INSERT INTO index_jobs(material_id,strategy_json,status,created_at,updated_at)
            SELECT mi.material_id,mi.strategy_json,'queued',?,?
            FROM material_index mi JOIN materials m ON m.id=mi.material_id
            WHERE m.status='active' AND mi.active_generation=0
              AND NOT EXISTS (SELECT 1 FROM index_jobs j WHERE j.material_id=mi.material_id)
        """, (stamp, stamp))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def enqueue(conn: sqlite3.Connection, material_id: int, strategy: dict) -> dict:
    """Queue or safely update a queued rebuild; never replace a running strategy."""
    stamp = utc_now()
    payload = json.dumps(strategy, ensure_ascii=False, sort_keys=True)
    conn.execute("BEGIN IMMEDIATE")
    try:
        busy = conn.execute(
            "SELECT id,status,strategy_json FROM index_jobs "
            "WHERE material_id=? AND status IN ('queued','running') "
            "ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END,id DESC LIMIT 1",
            (material_id,),
        ).fetchone()
        if busy:
            current = json.loads(busy["strategy_json"])
            if busy["status"] == "running" and current != strategy:
                conn.execute("ROLLBACK")
                raise IndexTaskRunning(int(busy["id"]), current)
            updated = False
            if busy["status"] == "queued" and current != strategy:
                conn.execute(
                    "UPDATE index_jobs SET strategy_json=?,last_error=NULL,updated_at=? WHERE id=?",
                    (payload, stamp, busy["id"]),
                )
                conn.execute(
                    "UPDATE material_index SET status='pending',last_error=NULL,updated_at=? "
                    "WHERE material_id=?",
                    (stamp, material_id),
                )
                updated = True
            conn.execute("COMMIT")
            return {
                "job_id": int(busy["id"]),
                "status": str(busy["status"]),
                "strategy": strategy if updated else current,
                "updated_existing": updated,
            }
        conn.execute("""
            INSERT OR IGNORE INTO material_index(material_id,status,strategy_json,updated_at)
            VALUES (?, 'pending', ?, ?)
        """, (material_id, json.dumps(AUTO_STRATEGY, sort_keys=True), stamp))
        cursor = conn.execute("""
            INSERT INTO index_jobs(material_id,strategy_json,status,created_at,updated_at)
            VALUES (?,?,'queued',?,?)
        """, (material_id, payload, stamp, stamp))
        # strategy_json on material_index describes the active generation. The requested
        # strategy remains on index_jobs until the new generation is committed.
        conn.execute("UPDATE material_index SET status='pending',last_error=NULL,updated_at=? WHERE material_id=?",
                     (stamp, material_id))
        conn.execute("COMMIT")
        return {
            "job_id": int(cursor.lastrowid),
            "status": "queued",
            "strategy": strategy,
            "updated_existing": False,
        }
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


class IndexTaskRunning(Exception):
    """A running rebuild cannot be replaced with a different strategy."""

    def __init__(self, job_id: int, strategy: dict):
        super().__init__("an index rebuild is already running")
        self.job_id = job_id
        self.strategy = strategy


def _decode_strategy(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _job_is_stalled(status: str, updated_at: str | None) -> bool:
    if not updated_at:
        return False
    try:
        stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    threshold = QUEUED_WORKER_HINT_SECONDS if status == "queued" else STALL_SECONDS
    return (datetime.now(timezone.utc) - stamp).total_seconds() > threshold


def index_status(conn: sqlite3.Connection, material_id: int) -> dict:
    row = conn.execute(
        "SELECT active_generation,status,strategy_json,last_error,updated_at "
        "FROM material_index WHERE material_id=?", (material_id,)
    ).fetchone()
    active_generation = int(row["active_generation"]) if row else 0
    active_strategy = None
    if active_generation:
        active = conn.execute(
            "SELECT strategy_json FROM knowledge_chunks WHERE material_id=? "
            "AND generation=? AND index_status='ready' ORDER BY chunk_index LIMIT 1",
            (material_id, active_generation),
        ).fetchone()
        active_strategy = _decode_strategy(active["strategy_json"]) if active else None
        if active_strategy is None and row:
            active_strategy = _decode_strategy(row["strategy_json"])
    pending_row = conn.execute(
        "SELECT id,status,strategy_json,created_at,updated_at FROM index_jobs "
        "WHERE material_id=? AND status IN ('queued','running') "
        "ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END,id DESC LIMIT 1",
        (material_id,),
    ).fetchone()
    pending = None
    if pending_row:
        pending_status = str(pending_row["status"])
        updated_at = str(pending_row["updated_at"] or pending_row["created_at"])
        pending = {
            "job_id": int(pending_row["id"]),
            "status": pending_status,
            "strategy": _decode_strategy(pending_row["strategy_json"]),
            "updated_at": updated_at,
            "worker_stalled": _job_is_stalled(pending_status, updated_at),
        }
    return {
        "status": str(row["status"]) if row else "pending",
        "active_generation": active_generation,
        "active_strategy": active_strategy,
        "pending": pending,
        "worker_stalled": bool(pending and pending["worker_stalled"]),
        "last_error": row["last_error"] if row else None,
        "updated_at": row["updated_at"] if row else None,
        "recorded": row is not None,
    }


#: 索引状态超过这么久没变化，就认为没有服务在消费队列。
#: 取 120 秒：本机实测正常降级重建在 10 秒内完成（见 reports/user-trial-record.md），
#: 两分钟纹丝不动，基本可以断定索引服务没起来，而不是「还在切分」。
STALL_SECONDS = 120
QUEUED_WORKER_HINT_SECONDS = 30


def index_status_map(conn: sqlite3.Connection, class_id: int) -> dict[int, dict | None]:
    """本班每份 active 材料的索引状态；``None`` 表示**从未入队**。

    与 ``index_status`` 的区别：那个把「没有记录」当成 ``pending``，
    于是一份根本没进队列的材料和一份正在排队等 worker 的材料长得完全一样。
    这两件事的处置完全不同——前者是上传链路断了，后者只是等一会儿——
    界面上也不该显示成同一个样子。
    """
    rows = conn.execute(
        """SELECT m.id AS material_id, mi.status, mi.last_error, mi.updated_at
             FROM materials m
             LEFT JOIN material_index mi ON mi.material_id = m.id
            WHERE m.class_id = ? AND m.status = 'active'""",
        (class_id,),
    ).fetchall()
    result = {}
    for row in rows:
        material_id = int(row["material_id"])
        state = index_status(conn, material_id)
        result[material_id] = state if state["recorded"] or state["pending"] else None
    return result
