"""第 10 课判据「运行观测」：监控面板与结构化观测接口。

三根支柱里，``/metrics`` 解决「有数据」，``request_id`` 解决「能串起来」，
本模块解决「有人判读」：

* ``GET /claw/``              —— 服务端渲染的面板（课件规定的路径），教师可见
* ``GET /dashboard``          —— 同一处理函数的兼容入口，早期文档与用例引用的是它
* ``GET /api/observability``  —— 同一份数据的 JSON 出口，供面板轮询与外部巡检
* ``GET /api/observability/series`` —— 按技能分线的曲线数据，支持时间轴缩放

权限与审计页一致：教师可见，学生一律挡掉。面板上的明细行（拒绝记录）按班级隔离，
聚合计数（延迟、索引失败数、任务积压）属于服务健康度，不分班。
"""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from campusclaw import audit_db, observability, timeseries
from campusclaw import request_context as rc
from campusclaw.errors import ApiError, MESSAGES

bp = Blueprint("dashboard", __name__)


def _require_teacher_api() -> dict:
    """JSON 接口权限链：认证 → 仅教师。"""
    user = rc.require_api_auth()
    if user["role"] != "teacher":
        raise ApiError(403, "ROLE_FORBIDDEN", MESSAGES["ROLE_FORBIDDEN"])
    return user


@bp.get("/claw/")
def dashboard_page():
    """监控面板。学生重定向到材料页——面板是运维视角，不是学生功能。

    ``/claw/`` 是课件规定的路径；``/dashboard`` 由 :func:`dashboard_legacy`
    转进来，早期文档、截图与用例都指向它，换路径不该让既有链接失效。

    ``?request_id=`` 为追踪回查入口：把一次请求的审计段与技能调用段按时间串起来。
    """
    user = rc.require_page_auth()
    if user["role"] != "teacher":
        return redirect(url_for("pages.materials_page"))
    conn = rc.get_conn()
    data = observability.collect(conn, class_id=int(user["class_id"]))
    wanted = (request.args.get("request_id") or "").strip()[: audit_db.MAX_REQUEST_ID]
    trace = None
    if wanted:
        trace = audit_db.trace_request(conn, wanted)
        class_id = int(user["class_id"])
        trace["steps"] = [
            s for s in trace["steps"]
            if s["class_id"] is None or int(s["class_id"]) == class_id
        ]
        trace["count"] = len(trace["steps"])
        trace["found"] = bool(trace["steps"])
        for step in trace["steps"]:
            step.pop("class_id", None)
    # 首屏就把默认档位的曲线渲染进去：等 JS 拉一次再画，会先闪一块空白。
    series = timeseries.collect(conn, int(user["class_id"]), timeseries.DEFAULT_RANGE)
    return render_template(
        "dashboard.html", user=user, data=data, trace=trace, series=series,
        trace_query=wanted, csrf_token=rc.ensure_csrf_token()
    )


@bp.get("/claw")
def claw_no_slash():
    """``/claw`` 补尾斜杠，保留查询串（回查 request_id 时不能丢参数）。"""
    query = request.query_string.decode("utf-8", "ignore")
    return redirect(url_for("dashboard.dashboard_page") + (("?" + query) if query else ""))


@bp.get("/dashboard", endpoint="dashboard_legacy")
def dashboard_legacy():
    """兼容入口：渲染同一张面板，不重定向。

    早期用例断言教师访问 ``/dashboard`` 得到 200 且页面含关键区块；改成 302 会让
    那些用例失败——「通过」与否取决于真实行为，不该为了路径整齐把它们改绿。
    """
    return dashboard_page()


@bp.get("/api/observability")
def observability_api():
    """面板轮询用的 JSON 快照；结构与面板服务端渲染时完全一致。"""
    user = _require_teacher_api()
    data = observability.collect(rc.get_conn(), class_id=int(user["class_id"]))
    return jsonify(data), 200


@bp.get("/api/observability/series")
def series_api():
    """曲线数据：``?range=1h|6h|24h|7d``，未知档位退回默认而不是报错。

    时间轴缩放必须由服务端按档位重新分桶——前端拿 60 个一分钟的桶画不出
    「今天」，把一分钟桶加总成十分钟桶又会把 P95 算错（分位数不能相加）。
    """
    user = _require_teacher_api()
    spec = (request.args.get("range") or timeseries.DEFAULT_RANGE).strip()
    payload = timeseries.collect(rc.get_conn(), int(user["class_id"]), spec)
    return jsonify(payload), 200
