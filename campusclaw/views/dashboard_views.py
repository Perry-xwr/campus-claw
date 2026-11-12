"""第 10 课判据「运行观测」：监控面板与结构化观测接口。

三根支柱里，``/metrics`` 解决「有数据」，``request_id`` 解决「能串起来」，
本模块解决「有人判读」：

* ``GET /dashboard``        —— 服务端渲染的面板，教师可见
* ``GET /api/observability`` —— 同一份数据的 JSON 出口，供面板轮询与外部巡检

权限与审计页一致：教师可见，学生一律挡掉。面板上的明细行（拒绝记录）按班级隔离，
聚合计数（延迟、索引失败数、任务积压）属于服务健康度，不分班。
"""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, url_for

from campusclaw import observability
from campusclaw import request_context as rc
from campusclaw.errors import ApiError, MESSAGES

bp = Blueprint("dashboard", __name__)


def _require_teacher_api() -> dict:
    """JSON 接口权限链：认证 → 仅教师。"""
    user = rc.require_api_auth()
    if user["role"] != "teacher":
        raise ApiError(403, "ROLE_FORBIDDEN", MESSAGES["ROLE_FORBIDDEN"])
    return user


@bp.get("/dashboard")
def dashboard_page():
    """监控面板。学生重定向到材料页——面板是运维视角，不是学生功能。"""
    user = rc.require_page_auth()
    if user["role"] != "teacher":
        return redirect(url_for("pages.materials_page"))
    data = observability.collect(rc.get_conn(), class_id=int(user["class_id"]))
    return render_template(
        "dashboard.html", user=user, data=data, csrf_token=rc.ensure_csrf_token()
    )


@bp.get("/api/observability")
def observability_api():
    """面板轮询用的 JSON 快照；结构与面板服务端渲染时完全一致。"""
    user = _require_teacher_api()
    data = observability.collect(rc.get_conn(), class_id=int(user["class_id"]))
    return jsonify(data), 200
