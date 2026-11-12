"""匿名健康检查与指标出口：不依赖登录，只做只读探测。"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify

from campusclaw import db as dbmod
from campusclaw import metrics
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
