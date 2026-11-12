"""第 10 课判据「运行观测」：把指标收敛成健康状态与告警。

课件说「放心 = 出问题能在用户发现之前看到」，三根支柱是**指标、日志、追踪**。
本项目已有 ``/metrics``（指标出口）与 ``request_id``（追踪），缺的是第三个：
**没有人判读**。有数据源不等于有人看，看的人也不该每天手工比对阈值。

本模块补这一层，两条出口共用同一份判定逻辑：

* :func:`evaluate` —— 规则引擎，把当前事实判成 ``ok`` / ``degraded`` / ``critical``
* :func:`collect`  —— 面板所需的全部数据（指标快照 + 库内事实 + 告警结果）

阈值集中在 :data:`THRESHOLDS`，调阈值不用改判定逻辑。规则分两档：

* ``critical`` —— 已经坏了，不必等用户报障（索引失败、库不可用）
* ``warning``  —— 还没坏，但趋势不对（延迟升高、任务积压、拒绝数异常增长）
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from campusclaw import cache
from campusclaw import db as dbmod
from campusclaw import metrics

#: 判定阈值。改这里即可调整灵敏度，不必动规则代码。
THRESHOLDS: dict[str, float] = {
    # 索引失败的材料数上限：>0 即为 critical。DEF-01 的教训——失败一次就永久不可检索。
    "index_failed": 0,
    # 待处理任务积压上限，超过说明 worker 跟不上或已停摆。
    "tasks_pending": 50,
    # 延迟 P95 上限（毫秒）。样本不足时跳过，避免冷启动几次慢请求就报红。
    "p95_ms": 500.0,
    "p95_min_samples": 20,
    # 时间窗内被拒绝次数上限，超过说明可能正在被刷。
    "denials_window_min": 60,
    "denials_max": 200,
}

#: critical 排在前面，面板按严重度展示。
_LEVEL_ORDER = {"critical": 0, "warning": 1}


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _scalar(conn: sqlite3.Connection, sql: str, default: int = 0) -> int:
    """宽容取单个整数：表不存在或数据异常时返回默认值，不让监控本身把请求打挂。"""
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


def _rule(rule_id: str, level: str, title: str, value: Any, threshold: Any,
          ok: bool, hint: str, skipped: bool = False) -> dict[str, Any]:
    """一条规则的三态结果：通过 / 未通过 / 跳过。

    ``skipped`` 与 ``ok`` 不是一回事：样本不足时判「跳过」，不判「通过」。
    早先把样本不足直接算通过，面板上就是一条绿色的「请求 P95 延迟 0.0」——
    零样本必然满足阈值，这种绿是假绿，会让人以为指标在正常范围内。
    判据表里「没人试过」既不是红也不是绿，这里同理。
    """
    return {
        "id": rule_id,
        "level": level,
        "title": title,
        "value": value,
        "threshold": threshold,
        "ok": bool(ok),
        "skipped": bool(skipped),
        "hint": hint,
    }


def _check_db(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        ok = bool(dbmod.health_probe(conn))
    except Exception:
        ok = False
    return _rule("db_probe", "critical", "数据库可用", "ok" if ok else "fail", "ok", ok,
                 "库不可用时所有接口都会失败，先恢复服务再谈其他指标")


def _check_index_failed(conn: sqlite3.Connection) -> dict[str, Any]:
    failed = _scalar(conn, "SELECT COUNT(*) FROM material_index WHERE status = 'failed'")
    limit = int(THRESHOLDS["index_failed"])
    return _rule("index_failed", "critical", "索引失败的材料数", failed, limit,
                 failed <= limit,
                 "失败的材料对学生不可检索；检查 worker 日志与 embedding 配置")


def _check_tasks_pending(conn: sqlite3.Connection) -> dict[str, Any]:
    pending = _scalar(conn, "SELECT COUNT(*) FROM grade_tasks WHERE status = 'pending'")
    limit = int(THRESHOLDS["tasks_pending"])
    return _rule("tasks_pending", "warning", "待处理任务数", pending, limit, pending <= limit,
                 "积压持续上升说明 worker 跟不上或已停摆")


def _check_latency(snapshot: dict[str, Any]) -> dict[str, Any]:
    duration = snapshot.get("duration_ms") or {}
    samples = int(duration.get("samples") or 0)
    p95 = float(duration.get("p95") or 0.0)
    limit = float(THRESHOLDS["p95_ms"])
    min_samples = int(THRESHOLDS["p95_min_samples"])
    if samples < min_samples:
        # 样本不足不下结论：冷启动阶段几次慢请求会把 P95 拉高，误报比漏报更消耗信任。
        # 但也不许判「通过」——零样本时 P95 恒为 0，必然满足阈值，那是假绿。
        return _rule("http_p95_ms", "warning", "请求 P95 延迟（毫秒）",
                     round(p95, 2) if samples else "无样本", limit, True,
                     f"样本 {samples} 条，少于 {min_samples} 条，暂不判定",
                     skipped=True)
    return _rule("http_p95_ms", "warning", "请求 P95 延迟（毫秒）", round(p95, 2), limit,
                 p95 <= limit, "先看是哪条路径慢，再看是否缺索引或下游超时")


def _check_denials(conn: sqlite3.Connection) -> dict[str, Any]:
    window = int(THRESHOLDS["denials_window_min"])
    limit = int(THRESHOLDS["denials_max"])
    cutoff = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=window))
    # ts 存的是 UTC ISO 字符串，取前 19 位比较可避开微秒位长短不一的边界问题。
    count = _scalar(
        conn,
        "SELECT COUNT(*) FROM audit_events WHERE substr(ts, 1, 19) >= '" + cutoff + "'",
    )
    return _rule("audit_denials", "warning", f"最近 {window} 分钟被拒绝请求数", count, limit,
                 count <= limit, "突增可能是被扫描或被刷；到审计页按 status / actor 下钻")


def evaluate(conn: sqlite3.Connection, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """跑全部规则，返回健康状态与未通过的告警项。

    ``status`` 取所有未通过规则里最严重的一档：有 critical 即 critical，
    否则有 warning 即 degraded，全通过为 ok。
    """
    snap = snapshot if snapshot is not None else metrics.snapshot()
    rules = [
        _check_db(conn),
        _check_index_failed(conn),
        _check_tasks_pending(conn),
        _check_latency(snap),
        _check_denials(conn),
    ]
    alerts = [r for r in rules if not r["ok"] and not r["skipped"]]
    alerts.sort(key=lambda r: _LEVEL_ORDER.get(r["level"], 9))
    skipped = [r for r in rules if r["skipped"]]

    if any(a["level"] == "critical" for a in alerts):
        status = "critical"
    elif alerts:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "rule_count": len(rules),
        "passed": len(rules) - len(alerts) - len(skipped),
        "skipped": len(skipped),
        "alerts": alerts,
        "rules": rules,
    }


def _recent_denials(conn: sqlite3.Connection, limit: int = 10,
                    class_id: int | None = None) -> list[dict[str, Any]]:
    """最近的拒绝记录。带 class_id 时只返回本班或未归属的记录。

    明细行带操作人与路径，跨班可见就是越权，因此按班级隔离；
    聚合计数（延迟、失败数）是服务健康度，不分班。
    """
    sql = (
        "SELECT ts, actor, method, path, status, code, request_id, class_id "
        "FROM audit_events {where} ORDER BY ts DESC, id DESC LIMIT ?"
    )
    # 只取拒绝类状态码：audit_events 里还有 api.request 链路段（写请求留痕），
    # 那些是 2xx，混进「最近拒绝」会把真正要看的越权尝试挤出列表。
    conditions = ["status IN (401, 403, 404)"]
    params: list[Any] = []
    if class_id is not None:
        conditions.append("(class_id IS NULL OR class_id = ?)")
        params.append(int(class_id))
    where = "WHERE " + " AND ".join(conditions)
    params.append(int(limit))
    try:
        rows = conn.execute(sql.format(where=where), params).fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _denials_in_window(conn: sqlite3.Connection, class_id: int | None = None) -> int:
    window = int(THRESHOLDS["denials_window_min"])
    cutoff = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=window))
    clause = "substr(ts, 1, 19) >= '" + cutoff + "'"
    if class_id is not None:
        clause += f" AND (class_id IS NULL OR class_id = {int(class_id)})"
    return _scalar(conn, "SELECT COUNT(*) FROM audit_events WHERE " + clause)


def collect(conn: sqlite3.Connection, class_id: int | None = None) -> dict[str, Any]:
    """面板与 JSON 接口共用的完整快照。

    ``class_id`` 为 None 表示本地运维视角（脚本直接读库），不限班级；
    由登录会话传入具体班级时，明细行按班过滤。
    """
    snap = metrics.snapshot()
    verdict = evaluate(conn, snap)
    window = int(THRESHOLDS["denials_window_min"])

    if class_id is None:
        material_sql = (
            "SELECT class_id, COUNT(*) AS n FROM materials GROUP BY class_id ORDER BY class_id"
        )
        material_params: tuple = ()
    else:
        material_sql = "SELECT class_id, COUNT(*) AS n FROM materials WHERE class_id = ? GROUP BY class_id"
        material_params = (int(class_id),)

    try:
        material_rows = conn.execute(material_sql, material_params).fetchall()
    except sqlite3.Error:
        material_rows = []

    return {
        "status": verdict["status"],
        "checked_at": verdict["checked_at"],
        "scope": {"class_id": class_id if class_id is not None else "all"},
        "metrics": snap,
        "cache": cache.stats(),
        "db": {
            "materials_by_class": [
                {"class_id": int(r[0]), "count": int(r[1])} for r in material_rows
            ],
            "materials_total": sum(int(r[1]) for r in material_rows),
            "index_ready": _scalar(
                conn, "SELECT COUNT(*) FROM material_index WHERE status = 'ready'"),
            "index_failed": _scalar(
                conn, "SELECT COUNT(*) FROM material_index WHERE status = 'failed'"),
            "tasks_pending": _scalar(
                conn, "SELECT COUNT(*) FROM grade_tasks WHERE status = 'pending'"),
            "audit_events_total": _scalar(conn, "SELECT COUNT(*) FROM audit_events"),
            "denials_window": _denials_in_window(conn, class_id),
            "denials_window_min": window,
        },
        "alerts": verdict["alerts"],
        "rules": verdict["rules"],
        "rule_count": verdict["rule_count"],
        "passed": verdict["passed"],
        "skipped": verdict["skipped"],
        "recent_denials": _recent_denials(conn, class_id=class_id),
        "thresholds": dict(THRESHOLDS),
    }
