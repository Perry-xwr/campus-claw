"""匿名健康检查与指标出口：不依赖登录，只做只读探测。"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify

from campusclaw import db as dbmod
from campusclaw import metrics
from campusclaw import observability
from campusclaw import request_context as rc

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    try:
        conn = rc.get_conn()
        ok = dbmod.health_probe(conn)
    except Exception:
        ok = False
    status = 200 if ok else 503
    return jsonify({"status": "ok" if ok else "unavailable"}), status


@bp.get("/metrics")
def metrics_endpoint():
    """Prometheus 文本格式指标；供监控面板抓取（第 10 课观测判据的数据源）。

    只输出计数与耗时，不含账号、令牌、材料内容等敏感信息，故与 /health 同样匿名。
    """
    try:
        body = metrics.render(rc.get_conn())
    except Exception:
        body = "campusclaw_up 0\n"
    return Response(body, status=200, mimetype="text/plain; version=0.0.4; charset=utf-8")


@bp.get("/api/health/alerts")
def alerts_endpoint():
    """告警判定出口：把指标判成 ok / degraded / critical。

    与 /metrics 同样匿名，理由相同——只回规则名、阈值与计数，不含任何账号或内容。
    外部巡检（``scripts/check_observe.py``）与容器探针靠它判断服务是否健康；
    带明细的面板走 /api/observability，那个需要教师身份。

    注意：HTTP 状态码恒为 200。告警状态放在正文的 ``status`` 字段里——
    监控要能区分「服务活着但不健康」和「服务挂了」，前者返回 503 会和
    「进程不在」混为一谈，反而丢失信息。
    """
    try:
        conn = rc.get_conn()
        verdict = observability.evaluate(conn)
    except Exception:
        return jsonify({"status": "critical", "checked_at": "", "rule_count": 0,
                        "passed": 0, "alerts": [], "rules": []}), 200
    return jsonify(verdict), 200
