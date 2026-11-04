"""服务端渲染页面。上传目录不挂载为静态目录。"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for

from campusclaw import materials as svc
from campusclaw import request_context as rc
from campusclaw.errors import raise_api

bp = Blueprint("pages", __name__, url_prefix="")


@bp.get("/")
def index():
    return redirect(url_for("pages.materials_page"))


@bp.get("/materials")
def materials_page():
    user = rc.require_page_auth()
    conn = rc.get_conn()
    items = svc.list_materials(conn, int(user["class_id"]))
    token = rc.ensure_csrf_token()
    return render_template(
        "materials.html",
        user=user,
        items=items,
        csrf_token=token,
    )


@bp.get("/knowledge")
def knowledge_page():
    user = rc.require_page_auth()
    items = svc.list_materials(rc.get_conn(), int(user["class_id"]))
    return render_template("knowledge.html", user=user, items=items,
                           csrf_token=rc.ensure_csrf_token())


@bp.get("/tutor")
def tutor_page():
    """解题助手：会话列表 + SSE 流式回答 + 引用出处。"""
    user = rc.require_page_auth()
    return render_template(
        "tutor.html", user=user, csrf_token=rc.ensure_csrf_token()
    )


@bp.get("/tutor/settings")
def tutor_settings_page():
    """教师设置：本班提示词 + 解题引导技能维护。学生重定向到助手页。"""
    user = rc.require_page_auth()
    if user["role"] != "teacher":
        return redirect(url_for("pages.tutor_page"))
    return render_template(
        "tutor_settings.html", user=user, csrf_token=rc.ensure_csrf_token()
    )


@bp.get("/mcp")
def mcp_page():
    """教师 MCP 管理：服务器登记/连接/断开/已发现工具/调用审计。学生重定向到助手页。"""
    user = rc.require_page_auth()
    if user["role"] != "teacher":
        return redirect(url_for("pages.tutor_page"))
    return render_template(
        "mcp.html", user=user, csrf_token=rc.ensure_csrf_token()
    )


# 上传目录不对外提供静态访问；显式 404，避免误以为存在公开路径。
@bp.get("/uploads/<path:storage_key>")
def uploads_static_denied(storage_key: str):  # noqa: ARG001
    raise_api("NOT_FOUND", 404)


@bp.get("/static/uploads/<path:storage_key>")
def static_uploads_denied(storage_key: str):  # noqa: ARG001
    raise_api("NOT_FOUND", 404)
