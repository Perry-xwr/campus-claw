"""第 8 课：异步批改任务的持久化记录、幂等结果与事务性发件箱。

课件 queue.html 允许「不用独立消息代理，改用数据库任务表 + 定时扫描」达到三条判据，
代价是行级抢占、超时回收、退避与死信要自己实现——本模块就是这部分实现。

三条不变量：
1. 提交记录与任务记录写在同一个事务里（transactional outbox），不会出现「只写了一半」。
2. 幂等键由业务含义派生并落在结果表的 UNIQUE 约束上，去重发生在「写入结果」那一刻。
3. 状态接口只读，连续查询不增加 attempts、不触发任何执行。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from campusclaw import db as dbmod

TERMINAL_STATES = ("succeeded", "dead")


class TaskInputError(ValueError):
    """不可重试的输入错误（permanent）。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="microseconds")


def ensure_schema(conn: sqlite3.Connection) -> None:
    """幂等增量建表；对既有库只新增表与索引，不改任何一行已有数据。"""
    with dbmod.transaction(conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS grade_submissions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id       INTEGER NOT NULL REFERENCES classes(id),
                user_id        INTEGER NOT NULL REFERENCES users(id),
                assignment_ref TEXT NOT NULL,
                content        TEXT NOT NULL,
                content_hash   TEXT NOT NULL,
                version        INTEGER NOT NULL DEFAULT 1,
                created_at     TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_grade_submission_identity
            ON grade_submissions(class_id, user_id, assignment_ref, content_hash, version)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS grade_tasks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id          TEXT NOT NULL UNIQUE,
                submission_id    INTEGER NOT NULL REFERENCES grade_submissions(id),
                class_id         INTEGER NOT NULL,
                user_id          INTEGER NOT NULL,
                idempotency_key  TEXT NOT NULL UNIQUE,
                status           TEXT NOT NULL
                    CHECK (status IN ('pending','running','succeeded','failed','dead')),
                attempts         INTEGER NOT NULL DEFAULT 0,
                max_attempts     INTEGER NOT NULL DEFAULT 3,
                error            TEXT,
                error_kind       TEXT CHECK (error_kind IN ('transient','permanent')),
                next_retry_at    TEXT,
                started_at       TEXT,
                finished_at      TEXT,
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_grade_tasks_claim
            ON grade_tasks(status, id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS grade_results (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key  TEXT NOT NULL UNIQUE,
                submission_id    INTEGER NOT NULL REFERENCES grade_submissions(id),
                task_id          TEXT NOT NULL,
                score            INTEGER NOT NULL,
                feedback         TEXT NOT NULL,
                created_at       TEXT NOT NULL
            )
        """)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def submit(conn: sqlite3.Connection, *, class_id: int, user_id: int,
           assignment_ref: str, content: str, version: int = 1) -> dict[str, Any]:
    """事务性发件箱：提交记录与任务记录同事务写入，返回 202 需要的凭证。

    同一 (班级, 用户, 作业, 内容, 版本) 重复提交只会得到同一个 task_id——
    这既覆盖用户重复点击，也覆盖网络重放。响应不含评分结果。
    """
    stamp = utc_now()
    digest = _content_hash(content)
    with dbmod.transaction(conn):
        conn.execute("""
            INSERT OR IGNORE INTO grade_submissions
                (class_id,user_id,assignment_ref,content,content_hash,version,created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (class_id, user_id, assignment_ref, content, digest, version, stamp))
        row = conn.execute("""
            SELECT id FROM grade_submissions
            WHERE class_id=? AND user_id=? AND assignment_ref=? AND content_hash=? AND version=?
        """, (class_id, user_id, assignment_ref, digest, version)).fetchone()
        submission_id = int(row["id"])
        idempotency_key = f"grade:{submission_id}:v{version}"
        conn.execute("""
            INSERT OR IGNORE INTO grade_tasks
                (task_id,submission_id,class_id,user_id,idempotency_key,status,
                 attempts,max_attempts,created_at,updated_at)
            VALUES (?,?,?,?,?,'pending',0,?,?,?)
        """, (
            "task_" + secrets.token_hex(8), submission_id, class_id, user_id,
            idempotency_key, _max_attempts(), stamp, stamp,
        ))
        task = conn.execute(
            "SELECT task_id,status,attempts FROM grade_tasks WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "attempts": int(task["attempts"]),
        "status_url": f"/api/tasks/{task['task_id']}",
    }


def _max_attempts() -> int:
    try:
        return max(1, min(10, int(os.environ.get("CAMPUSCLAW_TASK_MAX_ATTEMPTS", "3"))))
    except ValueError:
        return 3


def status_for(conn: sqlite3.Connection, task_id: str, class_id: int) -> dict[str, Any] | None:
    """只读状态查询。跨班与不存在统一返回 None，由视图转成 404。"""
    task = conn.execute("""
        SELECT t.task_id,t.status,t.attempts,t.max_attempts,t.error,t.error_kind,
               t.next_retry_at,t.started_at,t.finished_at,t.created_at,t.updated_at,
               t.idempotency_key,t.submission_id,
               s.assignment_ref,s.content,
               r.score,r.feedback,r.created_at AS result_created_at
        FROM grade_tasks t
        JOIN grade_submissions s ON s.id=t.submission_id
        LEFT JOIN grade_results r ON r.idempotency_key=t.idempotency_key
        WHERE t.task_id=? AND t.class_id=?
    """, (task_id, class_id)).fetchone()
    if task is None:
        return None
    result = None
    if task["score"] is not None:
        result = {
            "score": int(task["score"]),
            "feedback": task["feedback"],
            "created_at": task["result_created_at"],
        }
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "attempts": int(task["attempts"]),
        "max_attempts": int(task["max_attempts"]),
        "assignment_ref": task["assignment_ref"],
        "result": result,
        "error": task["error"],
        "error_kind": task["error_kind"],
        "next_retry_at": task["next_retry_at"],
        "started_at": task["started_at"],
        "finished_at": task["finished_at"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


def claim(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """竞争消费：BEGIN IMMEDIATE 保证一条任务只被一个消费者认领。

    可认领：pending，或到点了的可重试 failed。running 的任务不会被别人抢走，
    直到 recover_stale() 在 worker 启动时把崩溃遗留的 running 放回 pending。
    """
    now = utc_now()
    with dbmod.transaction(conn):
        row = conn.execute("""
            SELECT t.*, s.content, s.assignment_ref
            FROM grade_tasks t
            JOIN grade_submissions s ON s.id=t.submission_id
            WHERE t.status='pending'
               OR (t.status='failed' AND t.error_kind='transient'
                   AND t.attempts < t.max_attempts
                   AND t.next_retry_at IS NOT NULL AND t.next_retry_at <= ?)
            ORDER BY t.id LIMIT 1
        """, (now,)).fetchone()
        if row is None:
            return None
        conn.execute("""
            UPDATE grade_tasks
            SET status='running', attempts=attempts+1, started_at=?,
                error=NULL, error_kind=NULL, next_retry_at=NULL, updated_at=?
            WHERE id=?
        """, (now, now, row["id"]))
    return dict(row)


def recover_stale(conn: sqlite3.Connection) -> int:
    """至少一次语义：进程崩溃时未完成的任务回到 pending，等待重投。"""
    with dbmod.transaction(conn):
        cursor = conn.execute(
            "UPDATE grade_tasks SET status='pending', updated_at=? WHERE status='running'",
            (utc_now(),),
        )
        return int(cursor.rowcount)


def write_result(conn: sqlite3.Connection, task: dict[str, Any],
                 score: int, feedback: str) -> bool:
    """去重落在写入结果的语句上：重复投递被 UNIQUE 约束静默吸收。

    返回 True 表示本次真的写入了新结果，False 表示已有结果（重复执行）。
    """
    cursor = conn.execute("""
        INSERT OR IGNORE INTO grade_results
            (idempotency_key,submission_id,task_id,score,feedback,created_at)
        VALUES (?,?,?,?,?,?)
    """, (task["idempotency_key"], task["submission_id"], task["task_id"],
          score, feedback, utc_now()))
    return cursor.rowcount == 1


def complete(conn: sqlite3.Connection, task: dict[str, Any],
             score: int, feedback: str) -> bool:
    """写结果与标记成功在同一事务里；重复投递只会被 UNIQUE 约束吸收一次。

    返回 True 表示本次真的新增了一份结果；False 表示同一幂等键已有结果，
    状态照样收敛到 succeeded，但结果表不会多出一行。
    """
    with dbmod.transaction(conn):
        cursor = conn.execute("""
            INSERT OR IGNORE INTO grade_results
                (idempotency_key,submission_id,task_id,score,feedback,created_at)
            VALUES (?,?,?,?,?,?)
        """, (task["idempotency_key"], task["submission_id"], task["task_id"],
              score, feedback, utc_now()))
        inserted = cursor.rowcount == 1
        conn.execute("""
            UPDATE grade_tasks
            SET status='succeeded', error=NULL, error_kind=NULL,
                next_retry_at=NULL, finished_at=?, updated_at=?
            WHERE id=?
        """, (utc_now(), utc_now(), task["id"]))
    return inserted


def mark_succeeded(conn: sqlite3.Connection, task: dict[str, Any]) -> None:
    with dbmod.transaction(conn):
        conn.execute("""
            UPDATE grade_tasks
            SET status='succeeded', error=NULL, error_kind=NULL,
                next_retry_at=NULL, finished_at=?, updated_at=?
            WHERE id=?
        """, (utc_now(), utc_now(), task["id"]))


def mark_failed(conn: sqlite3.Connection, task: dict[str, Any],
                reason: str, kind: str) -> str:
    """失败分类 + 指数退避 + 抖动 + 次数上限转死信，返回落到的状态。"""
    attempts = int(task["attempts"])
    max_attempts = int(task["max_attempts"])
    permanent = kind == "permanent"
    exhausted = attempts >= max_attempts
    status = "dead" if (permanent or exhausted) else "failed"
    if status == "dead":
        next_retry = None
    else:
        # 1s, 2s, 4s ... 叠加 [0, 0.4s) 抖动，避免一批失败任务同时重试。
        import random
        base = min(30.0, float(2 ** max(0, attempts - 1)))
        next_retry = _after(base + random.uniform(0.0, 0.4))
    with dbmod.transaction(conn):
        conn.execute("""
            UPDATE grade_tasks
            SET status=?, error=?, error_kind=?, next_retry_at=?,
                finished_at=CASE WHEN ?='dead' THEN ? ELSE finished_at END,
                updated_at=?
            WHERE id=?
        """, (status, reason[:200], kind, next_retry, status, utc_now(),
              utc_now(), task["id"]))
    return status


def observations(conn: sqlite3.Connection, class_id: int | None = None) -> dict[str, Any]:
    """队列观测：积压、执行中、成功、死信、重试次数与平均执行耗时。"""
    where = "WHERE class_id=?" if class_id is not None else ""
    params: tuple[Any, ...] = (class_id,) if class_id is not None else ()
    rows = conn.execute(
        f"SELECT status, COUNT(*) AS n, SUM(attempts) AS total_attempts "
        f"FROM grade_tasks {where} GROUP BY status", params,
    ).fetchall()
    counts = {row["status"]: int(row["n"]) for row in rows}
    attempt_sum = sum(int(row["total_attempts"] or 0) for row in rows)
    duration = conn.execute(
        f"""SELECT AVG((julianday(finished_at)-julianday(started_at))*86400000) AS ms
            FROM grade_tasks {where + (' AND ' if where else 'WHERE ')}
            started_at IS NOT NULL AND finished_at IS NOT NULL""",
        params,
    ).fetchone()
    result_count = conn.execute("SELECT COUNT(*) AS n FROM grade_results").fetchone()["n"]
    return {
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "succeeded": counts.get("succeeded", 0),
        "failed": counts.get("failed", 0),
        "dead": counts.get("dead", 0),
        "total_attempts": attempt_sum,
        "avg_duration_ms": round(float(duration["ms"] or 0.0), 2),
        "results": int(result_count),
    }
