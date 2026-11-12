"""第 10 课判据「面板看得见技能」：把审计与任务表折叠成时间序列。

课件要求面板上至少三条曲线，且维度必须落到**技能**上：

* 每个技能的调用量（分线，不合计）
* 每个技能的错误率（三条线不互相平均）
* 接口 P95 与任务队列深度（并排看「接收得快不快、后台跟不跟得上」）

数据不从新表来：上一课为审计补的七列（``skill_id`` / ``status`` /
``duration_ms`` / ``ts``）就是指标字段，这里只做聚合。由此历史曲线在面板
第一次打开时就已经存在，不需要「先跑一天采样」才有图。

分桶而不是逐条画：一分钟一桶适合看「这一小时」，十分钟一桶适合看「今天」。
桶宽随 :data:`RANGES` 变化，前端只换参数，不改绘图代码。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

#: 时间轴缩放：名字 → (回看分钟数, 桶宽分钟数)。桶数控制在 60 个上下，
#: 再多画在 320px 高的画布上就挤成一团，看不出趋势。
RANGES: dict[str, tuple[int, int]] = {
    "1h": (60, 1),
    "6h": (360, 5),
    "24h": (1440, 10),
    "7d": (10080, 60),
}

DEFAULT_RANGE = "1h"

#: 未绑定技能标识的调用归到这一条线，不丢弃——丢掉就看不出总量去哪了。
UNLABELED = "（未标记）"

#: 单次查询的行数上限：七天内调用量再大，也不至于把面板拖成慢查询。
_ROW_CAP = 50000


def _parse(ts: str | None) -> datetime | None:
    """审计表里的时间戳统一是带时区的 ISO 字符串；解析失败按「无时间」处理。"""
    if not ts:
        return None
    try:
        moment = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def window(spec: str) -> tuple[str, int, int, datetime, datetime]:
    """把档位名解析成 (档位名, 回看分钟, 桶宽分钟, 起点, 终点)。未知档位退回默认。"""
    minutes, bucket = RANGES.get(spec or DEFAULT_RANGE, RANGES[DEFAULT_RANGE])
    name = spec if spec in RANGES else DEFAULT_RANGE
    now = datetime.now(timezone.utc)
    # 终点对齐到桶边界，桶宽 > 1 分钟时首个桶才不会是「半桶」。
    return name, minutes, bucket, now - timedelta(minutes=minutes), now


def _bucket_index(moment: datetime, start: datetime, bucket_minutes: int) -> int:
    return int((moment - start).total_seconds() // (bucket_minutes * 60))


def _labels(start: datetime, minutes: int, bucket_minutes: int) -> list[str]:
    """本地时区的桶标签；跨天时带上日期，避免「23:50 与 00:00」看不出换天。"""
    count = minutes // bucket_minutes
    out: list[str] = []
    for index in range(count + 1):
        moment = (start + timedelta(minutes=index * bucket_minutes)).astimezone()
        out.append(moment.strftime("%H:%M") if minutes <= 360 else moment.strftime("%m-%d %H:%M"))
    return out


def _rows(conn: sqlite3.Connection, sql: str, params: Iterable[Any]) -> list[sqlite3.Row]:
    """监控查询失败不向上抛：面板宁可少一条曲线，也不能因此打不开。"""
    try:
        return conn.execute(sql, tuple(params)).fetchmany(_ROW_CAP)
    except sqlite3.Error:
        return []


def skill_series(conn: sqlite3.Connection, class_id: int, spec: str) -> dict[str, Any]:
    """按技能分线的调用量与错误率。

    ``status`` 只有 ``ok`` / ``denied`` / ``error`` 三种；失败率把后两种算作失败，
    这是「结果状态」这一列的原始口径，不是另造一个指标。
    """
    name, minutes, bucket, start, _now = window(spec)
    size = minutes // bucket + 1
    labels = _labels(start, minutes, bucket)

    rows = _rows(
        conn,
        "SELECT created_at, skill_id, status FROM mcp_tool_calls "
        "WHERE class_id = ? AND created_at >= ? ORDER BY created_at",
        (int(class_id), start.isoformat()),
    )

    series: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        moment = _parse(row["created_at"])
        if moment is None:
            continue
        index = _bucket_index(moment, start, bucket)
        if not 0 <= index < size:
            continue
        label = (row["skill_id"] or "").strip() or UNLABELED
        slot = series.setdefault(label, {
            "invocations": [0] * size, "errors": [0] * size, "error_rate": [0.0] * size,
        })
        slot["invocations"][index] += 1
        if row["status"] != "ok":
            slot["errors"][index] += 1

    for slot in series.values():
        for index, total in enumerate(slot["invocations"]):
            slot["error_rate"][index] = round(slot["errors"][index] / total, 4) if total else 0.0

    ordered = sorted(
        series.items(), key=lambda item: (-sum(item[1]["invocations"]), item[0])
    )
    return {
        "buckets": labels,
        "skills": [{"name": label, **slot} for label, slot in ordered],
        "invocations": sum(sum(slot["invocations"]) for slot in series.values()),
        "errors": sum(sum(slot["errors"]) for slot in series.values()),
        "range": name,
        "bucket_minutes": bucket,
        "minutes": minutes,
    }


def latency_series(conn: sqlite3.Connection, class_id: int, spec: str) -> dict[str, Any]:
    """接口 P95（毫秒）按桶取分位。

    样本来自 ``audit_events.duration_ms``——那是请求处理耗时的落库值。桶内样本
    不足 3 条时输出 ``None`` 而不是 0：零样本画成 0 会让人以为「这一刻特别快」，
    实际是「这一刻没人用」。
    """
    name, minutes, bucket, start, _now = window(spec)
    size = minutes // bucket + 1
    labels = _labels(start, minutes, bucket)

    rows = _rows(
        conn,
        "SELECT ts, duration_ms FROM audit_events "
        "WHERE (class_id IS NULL OR class_id = ?) AND duration_ms IS NOT NULL "
        "AND ts >= ? ORDER BY ts",
        (int(class_id), start.isoformat()),
    )

    samples: list[list[float]] = [[] for _ in range(size)]
    for row in rows:
        moment = _parse(row["ts"])
        if moment is None:
            continue
        index = _bucket_index(moment, start, bucket)
        if 0 <= index < size:
            samples[index].append(float(row["duration_ms"]))

    values: list[float | None] = []
    for group in samples:
        if len(group) < 3:
            values.append(None)
            continue
        group.sort()
        position = (len(group) - 1) * 0.95
        low = int(position)
        high = min(low + 1, len(group) - 1)
        values.append(round(group[low] * (1 - (position - low)) + group[high] * (position - low), 2))

    return {
        "buckets": labels,
        "p95": values,
        "samples": sum(len(group) for group in samples),
        "range": name,
        "bucket_minutes": bucket,
        "minutes": minutes,
    }


def queue_series(conn: sqlite3.Connection, class_id: int, spec: str) -> dict[str, Any]:
    """任务队列深度（pending + running）随时间的形状。

    用「入队 +1、结束 -1」的扫线算每个桶末的深度，而不是每桶查一次 ``COUNT``：
    60 个桶就是 60 次查询，面板刷新一次打 60 条 SQL 不合理。
    """
    name, minutes, bucket, start, _now = window(spec)
    size = minutes // bucket + 1
    labels = _labels(start, minutes, bucket)

    rows = _rows(
        conn,
        "SELECT created_at, finished_at FROM grade_tasks WHERE class_id = ? "
        "AND (finished_at IS NULL OR finished_at >= ?) ORDER BY created_at",
        (int(class_id), start.isoformat()),
    )

    events: list[tuple[datetime, int]] = []
    baseline = 0
    for row in rows:
        created = _parse(row["created_at"])
        if created is None:
            continue
        if created < start:
            # 窗口开始前就压在队列里的任务：起点深度已经不为零。
            baseline += 1
            continue
        events.append((created, 1))
        finished = _parse(row["finished_at"])
        if finished is not None:
            events.append((finished, -1))
    events.sort(key=lambda item: (item[0], item[1]))

    depth: list[int] = []
    cursor = 0
    current = baseline
    for index in range(size):
        edge = start + timedelta(minutes=index * bucket)
        while cursor < len(events) and events[cursor][0] <= edge:
            current += events[cursor][1]
            cursor += 1
        depth.append(max(0, current))

    return {
        "buckets": labels,
        "depth": depth,
        "range": name,
        "bucket_minutes": bucket,
        "minutes": minutes,
    }


def collect(conn: sqlite3.Connection, class_id: int, spec: str) -> dict[str, Any]:
    """面板一次刷新所需的全部曲线，外加一个总数摘要。"""
    skills = skill_series(conn, class_id, spec)
    latency = latency_series(conn, class_id, spec)
    queue = queue_series(conn, class_id, spec)
    return {
        "range": skills["range"],
        "bucket_minutes": skills["bucket_minutes"],
        "minutes": skills["minutes"],
        "buckets": skills["buckets"],
        "skills": skills["skills"],
        "invocations": skills["invocations"],
        "errors": skills["errors"],
        "p95": latency["p95"],
        "latency_samples": latency["samples"],
        "queue": queue["depth"],
        "available_ranges": list(RANGES),
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
