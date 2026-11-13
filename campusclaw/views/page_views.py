"""服务端渲染页面。上传目录不挂载为静态目录。"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for

from campusclaw import materials as svc
from campusclaw import request_context as rc
from campusclaw import retrieval_db, timeutil
from campusclaw.errors import raise_api
from campusclaw.retrieval_config import RetrievalConfig

bp = Blueprint("pages", __name__, url_prefix="")

#: 索引状态 → 界面文案。``None``（从未入队）单独一档：那是上传链路断了，
#: 不是「还在排队」，两者的处置完全不同，不能显示成同一个样子。
_INDEX_LABELS = {
    "ready": ("已建索引", "badge-ok"),
    "pending": ("索引排队中", "badge-neutral"),
    "running": ("正在建索引", "badge-neutral"),
    "failed": ("索引失败", "badge-danger"),
    None: ("未进入索引队列", "badge-warn"),
}


def index_panel(conn, items: list[dict], class_id: int) -> dict:
    """给材料列表补索引状态，并判断索引服务是不是根本没在跑。

    为什么要在列表页做这件事：「上传成功」和「检索得到」中间隔着索引 worker，
    而这一环此前在界面上完全不可见。worker 没起时材料永远停在 pending，
    老师看到的现象只是「搜不到」，于是去怀疑编码、切分策略、自己的操作——
    实测中有人为此折腾了十分钟才发现后台服务没开。状态必须可见，
    卡住时必须把最可能的病因直接说出来，而不是让人自己猜。
    """
    states = retrieval_db.index_status_map(conn, class_id)
    now = timeutil.now_utc()
    worst_wait = 0
    unfinished = 0
    for item in items:
        state = states.get(int(item["id"]))
        status = None if state is None else state["status"]
        item["index_status"] = status
        item["index_error"] = None if state is None else state["last_error"]
        label, tone = _INDEX_LABELS.get(status, (str(status), "badge-neutral"))
        item["index_label"] = label
        item["index_tone"] = tone
        if status not in ("pending", "running"):
            continue
        unfinished += 1
        updated = (state or {}).get("updated_at")
        if not updated:
            continue
        try:
            waited = int((now - timeutil.parse_iso_loose(updated)).total_seconds())
        except (TypeError, ValueError):
            continue
        worst_wait = max(worst_wait, waited)
    return {
        "index_stalled": worst_wait > retrieval_db.STALL_SECONDS,
        "index_wait_minutes": max(1, worst_wait // 60) if worst_wait else 0,
        "index_unfinished": unfinished,
    }


@bp.get("/")
def index():
    return redirect(url_for("pages.materials_page"))


@bp.get("/m")
@bp.get("/m/")
def mobile_page():
    """第 10 课轻量端：手机浏览器直接打开的 H5。

    页面本身不渲染任何服务端数据，也不要求登录——它自己调 ``/api/login`` 拿令牌，
    与桌面端走完全相同的接口契约（202 + 任务标识、跨班 404、审计七列因此自动生效）。
    少一层服务端会话，就少一处「轻量端有、桌面端没有」的差异。
    """
    return render_template("h5.html")


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
        **index_panel(conn, items, int(user["class_id"])),
    )


@bp.get("/knowledge")
def knowledge_page():
    user = rc.require_page_auth()
    items = svc.list_materials(rc.get_conn(), int(user["class_id"]))
    # 检索方式的可选项由服务端能力决定，不让界面给出做不到的默认值：
    # 向量服务没配时，hybrid / vector 一定 503，而关键词路（FTS5）是可用的。
    # 默认选中一个必然失败的模式，等于把环境故障记到使用者账上。
    cfg = RetrievalConfig.from_env()
    return render_template("knowledge.html", user=user, items=items,
                           csrf_token=rc.ensure_csrf_token(),
                           embedding_ready=cfg.embedding_ready,
                           chat_ready=cfg.chat_ready)


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
