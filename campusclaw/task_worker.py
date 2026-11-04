"""第 8 课：独立消费者进程。

    uv run python -m campusclaw.task_worker             # 常驻
    uv run python -m campusclaw.task_worker --once      # 把当前可认领的任务跑完就退出

与 Web 服务完全解耦：停掉它，提交接口照常返回 202，任务留在 pending；
重新启动后崩溃遗留下来的 running 也会被 recover_stale 放回 pending 重投。
"""

from __future__ import annotations

import argparse
import logging
import os
import time

from campusclaw import db as dbmod, task_db
from campusclaw.config import load_project_dotenv, load_settings

LOG = logging.getLogger(__name__)


class TransientFailure(RuntimeError):
    """可重试失败：依赖暂时不可用，等一会儿再试有可能成功。"""


def _delay_ms() -> int:
    """演示用可控执行耗时。生产环境应换成真实模型调用，不需要这个开关。"""
    try:
        return max(0, min(60000, int(os.environ.get("CAMPUSCLAW_TASK_DELAY_MS", "0"))))
    except ValueError:
        return 0


def grade(content: str, delay_ms: int | None = None) -> tuple[int, str]:
    """确定性本地批改：不依赖任何外部模型，零配置也能复现三条判据。

    内容里的 TRANSIENT_FAIL / PERMANENT_FAIL 是验收用的故障注入开关，
    用来复现「可重试 → 退避 → 死信」与「不可重试 → 直接 dead」两条路径。
    """
    if delay_ms is None:
        delay_ms = _delay_ms()
    if "TRANSIENT_FAIL" in content:
        raise TransientFailure("注入：依赖暂时不可用")
    if "PERMANENT_FAIL" in content:
        raise task_db.TaskInputError("注入：提交内容不成立，重试必然同样失败")
    text = content.strip()
    if not text:
        raise task_db.TaskInputError("提交内容为空")
    if delay_ms:
        time.sleep(delay_ms / 1000.0)

    markers = ("因为", "所以", "解：", "答：", "步骤", "由此", "```", "=>")
    hits = [marker for marker in markers if marker in text]
    score = min(100, 60 + min(20, len(text) // 10) + 4 * len(hits))
    feedback = (
        f"已批改 {len(text)} 字作答；命中论证标记 {len(hits)} 个"
        f"（{'、'.join(hits) if hits else '无'}）；得分 {score}。"
        "本结果由确定性本地批改器生成，不依赖外部模型，可原样复现。"
    )
    return score, feedback


def process_one(conn, delay_ms: int | None = None) -> bool:
    """取一条、执行、写回、确认。返回 False 表示队列当前无可认领任务。"""
    task = task_db.claim(conn)
    if task is None:
        return False
    try:
        score, feedback = grade(task["content"], delay_ms)
        inserted = task_db.complete(conn, task, score, feedback)
        LOG.info("task=%s status=succeeded attempts=%s result_written=%s",
                 task["task_id"], int(task["attempts"]) + 1, inserted)
    except task_db.TaskInputError as exc:
        state = task_db.mark_failed(conn, task, str(exc), "permanent")
        LOG.warning("task=%s status=%s reason=%s", task["task_id"], state, exc)
    except Exception as exc:  # 依赖不可用、网络抖动等一律按 transient 处理
        state = task_db.mark_failed(conn, task, type(exc).__name__, "transient")
        LOG.warning("task=%s status=%s attempts=%s reason=%s",
                    task["task_id"], state, int(task["attempts"]) + 1, type(exc).__name__)
    return True


def run(*, once: bool = False, interval: float = 1.0,
        delay_ms: int | None = None, use_dotenv: bool = True) -> None:
    if use_dotenv:
        load_project_dotenv()
    settings = load_settings()
    conn = dbmod.connect(settings.db_path)
    try:
        task_db.ensure_schema(conn)
        recovered = task_db.recover_stale(conn)
        if recovered:
            LOG.info("recovered %s interrupted task(s) back to pending", recovered)
        while True:
            worked = process_one(conn, delay_ms)
            if once and not worked:
                break
            if not worked:
                time.sleep(interval)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CampusClaw 异步批改消费者")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--delay-ms", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(once=args.once, interval=args.interval, delay_ms=args.delay_ms, use_dotenv=True)
