"""第 10 课：指标出口（Prometheus 文本格式）。

课件要求「监控面板能画出四条曲线」，而曲线要有数据源。本项目原先没有任何
指标出口，面板无从取数，因此这里补一个最小可用的 ``/metrics``：

* 请求量 ``campusclaw_http_requests_total``（按方法、归一化路径、状态码）
* 请求耗时 ``campusclaw_http_request_duration_ms``（进程内最近 2000 次采样的分位）
* 材料数、索引失败数、任务积压、审计拒绝数、工具调用数与耗时

实现刻意保持简单：进程内累积 + 读库快照，不引第三方依赖、不加推送组件。
多进程部署时每个 worker 各自计数，需要聚合时由抓取端按实例标签汇总——这与
Prometheus 的常规用法一致，不需要应用内做全局聚合。
"""

from __future__ import annotations

import collections
import re
import sqlite3
import threading
import time
from typing import Any

_LOCK = threading.Lock()

#: (method, path, status) -> 次数
_COUNTER: collections.Counter[tuple[str, str, str]] = collections.Counter()

#: 最近 N 次请求耗时（毫秒），用于算分位；环形缓冲，内存占用固定。
_DURATIONS: collections.deque[float] = collections.deque(maxlen=2000)

#: 归一化路径：把纯数字段与 UUID 段替换为占位符，避免标签基数爆炸。
_ID_SEGMENT = re.compile(r"/(?:\d+|[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,})(?=/|$)")


def normalize_path(path: str) -> str:
    """把 ``/api/materials/12`` 归一化为 ``/api/materials/:id``。"""
    return _ID_SEGMENT.sub("/:id", path or "/")


def observe(method: str, path: str, status: int, duration_ms: float) -> None:
    """记录一次请求；由 after_request 钩子调用，不得抛异常。"""
    with _LOCK:
        _COUNTER[(method, normalize_path(path), str(status))] += 1
        _DURATIONS.append(float(duration_ms))


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = pos - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _scalar(conn: sqlite3.Connection, sql: str, default: int = 0) -> int:
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.Error:
        return default
    if row is None:
        return default
    try:
        return int(row[0] or 0)
    except (TypeError, ValueError):
        return default


def _esc(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(conn: sqlite3.Connection) -> str:
    """输出 Prometheus 文本格式；读库失败时降级为仅进程内指标。"""
    lines: list[str] = []
    with _LOCK:
        counter_items = sorted(_COUNTER.items())
        durations = sorted(_DURATIONS)

    lines.append("# HELP campusclaw_http_requests_total 已处理的 HTTP 请求总数")
    lines.append("# TYPE campusclaw_http_requests_total counter")
    for (method, path, status), count in counter_items:
        lines.append(
            "campusclaw_http_requests_total"
            f'{{method="{_esc(method)}",path="{_esc(path)}",status="{_esc(status)}"}} {count}'
        )

    lines.append("# HELP campusclaw_http_request_duration_ms 请求耗时（毫秒，最近 2000 次采样）")
    lines.append("# TYPE campusclaw_http_request_duration_ms summary")
    for q in (0.5, 0.9, 0.95, 0.99):
        lines.append(
            f'campusclaw_http_request_duration_ms{{quantile="{q}"}} '
            f"{_quantile(durations, q):.3f}"
        )
    lines.append(
        "campusclaw_http_request_duration_ms_count " + str(len(durations))
    )

    lines.append("# HELP campusclaw_materials_total 材料总数（按班级）")
    lines.append("# TYPE campusclaw_materials_total gauge")
    try:
        rows = conn.execute(
            "SELECT class_id, COUNT(*) AS n FROM materials GROUP BY class_id ORDER BY class_id"
        ).fetchall()
        for row in rows:
            lines.append(
                f'campusclaw_materials_total{{class_id="{int(row[0])}"}} {int(row[1])}'
            )
    except sqlite3.Error:
        pass

    lines.append("# HELP campusclaw_material_index_failed 索引状态为 failed 的材料数")
    lines.append("# TYPE campusclaw_material_index_failed gauge")
    lines.append(
        "campusclaw_material_index_failed "
        + str(_scalar(conn, "SELECT COUNT(*) FROM material_index WHERE status = 'failed'"))
    )

    lines.append("# HELP campusclaw_material_index_ready 索引就绪的材料数")
    lines.append("# TYPE campusclaw_material_index_ready gauge")
    lines.append(
        "campusclaw_material_index_ready "
        + str(_scalar(conn, "SELECT COUNT(*) FROM material_index WHERE status = 'ready'"))
    )

    lines.append("# HELP campusclaw_tasks_pending 待处理异步任务数")
    lines.append("# TYPE campusclaw_tasks_pending gauge")
    lines.append(
        "campusclaw_tasks_pending "
        + str(_scalar(conn, "SELECT COUNT(*) FROM grade_tasks WHERE status = 'pending'"))
    )

    lines.append("# HELP campusclaw_audit_denials_total 被拒绝的请求数（按状态码）")
    lines.append("# TYPE campusclaw_audit_denials_total counter")
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM audit_events GROUP BY status ORDER BY status"
        ).fetchall()
        for row in rows:
            lines.append(
                f'campusclaw_audit_denials_total{{status="{int(row[0])}"}} {int(row[1])}'
            )
    except sqlite3.Error:
        pass

    lines.append("# HELP campusclaw_mcp_tool_calls_total MCP 工具调用数（按状态）")
    lines.append("# TYPE campusclaw_mcp_tool_calls_total counter")
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM mcp_tool_calls GROUP BY status ORDER BY status"
        ).fetchall()
        for row in rows:
            lines.append(
                f'campusclaw_mcp_tool_calls_total{{status="{_esc(row[0])}"}} {int(row[1])}'
            )
    except sqlite3.Error:
        pass

    lines.append("# HELP campusclaw_mcp_tool_call_duration_ms_last 最近一次工具调用耗时（毫秒）")
    lines.append("# TYPE campusclaw_mcp_tool_call_duration_ms_last gauge")
    try:
        row = conn.execute(
            "SELECT tool_ref, duration_ms FROM mcp_tool_calls "
            "WHERE duration_ms IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            lines.append(
                f'campusclaw_mcp_tool_call_duration_ms_last{{tool="{_esc(row[0])}"}} {int(row[1])}'
            )
    except sqlite3.Error:
        pass

    lines.append("# HELP campusclaw_up 进程存活标记")
    lines.append("# TYPE campusclaw_up gauge")
    lines.append("campusclaw_up 1")
    return "\n".join(lines) + "\n"


def observe_from_g(g: Any, status: int) -> None:
    """从请求上下文 g 取起点与路径并记录；缺值则跳过。"""
    from flask import request

    started = getattr(g, "request_started", None)
    if started is None:
        return
    observe(request.method, request.path, status, (time.perf_counter() - started) * 1000)


def snapshot() -> dict[str, Any]:
    """进程内指标的结构化快照，供面板与告警判读使用。

    与 :func:`render` 读同一份数据，只是输出成 Python 结构而不是 Prometheus 文本：
    文本那是给抓取端用的，面板要自己算状态，不该再去解析自己生成的文本。
    """
    with _LOCK:
        counter_items = list(_COUNTER.items())
        durations = sorted(_DURATIONS)

    total = 0
    by_status: dict[str, int] = {}
    by_path: dict[str, int] = {}
    for (method, path, status), count in counter_items:
        total += count
        by_status[status] = by_status.get(status, 0) + count
        key = f"{method} {path}"
        by_path[key] = by_path.get(key, 0) + count

    return {
        "requests_total": total,
        "requests_by_status": dict(sorted(by_status.items())),
        "requests_by_path": dict(
            sorted(by_path.items(), key=lambda kv: kv[1], reverse=True)[:10]
        ),
        "duration_ms": {
            "samples": len(durations),
            "p50": round(_quantile(durations, 0.5), 2),
            "p90": round(_quantile(durations, 0.9), 2),
            "p95": round(_quantile(durations, 0.95), 2),
            "p99": round(_quantile(durations, 0.99), 2),
        },
    }
