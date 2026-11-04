"""CampusClaw 应用工厂。

浏览器 ←→ Flask App（认证、角色、班级、校验）←→ SQLite + 私有上传目录。
上传目录不作为静态目录对外暴露。
"""

from __future__ import annotations

import os
from typing import Any

from flask import Flask

from campusclaw import (
    bootstrap,
    db as dbmod,
    mcp_db,
    qa_db,
    retrieval_db,
    storage,
    task_db,
    timeutil,
    tutor_db,
)
from campusclaw.config import ConfigError, Settings, load_project_dotenv, load_settings
from campusclaw.errors import register_error_handlers
from campusclaw.request_context import close_conn, register_page_redirect

SESSION_COOKIE_NAME = "campusclaw_session"


class StartupError(Exception):
    """启动前置条件不满足：密钥缺失、数据库不完整或存储残留无法清理。"""


def prepare_storage_and_db(settings: Settings, env: dict[str, str] | None = None) -> None:
    """建库、幂等种子、启动恢复、待清理任务重试。全部在接收业务流量前完成。"""
    scenario = (env or {}).get("CAMPUSCLAW_TEST_SCENARIO", "") or os.environ.get(
        "CAMPUSCLAW_TEST_SCENARIO", ""
    )
    storage.ensure_directories(settings.upload_dir, settings.staging_dir)
    try:
        bootstrap.initialize(settings, env=env)
    except ConfigError:
        raise

    conn = dbmod.connect(settings.db_path)
    try:
        retrieval_db.ensure_schema(conn)
        tutor_db.ensure_schema(conn)
        # 第 6 课：MCP 三张表幂等增量建表，对既有数据无破坏。
        mcp_db.ensure_schema(conn)
        # 小组项目：班级答疑广场五张表幂等增量建表，不改既有表。
        qa_db.ensure_schema(conn)
        # 第 8 课：异步批改任务表、幂等结果表，幂等增量建表。
        task_db.ensure_schema(conn)
        # 为从未建立索引的材料补建关键词就绪切片，使解题助手开箱可检索本班资料。
        tutor_db.backfill_keyword_ready(conn)
        if scenario == "recovery_staging":
            staging = settings.staging_dir / "orphan.staging"
            staging.parent.mkdir(parents=True, exist_ok=True)
            staging.write_bytes(b"orphan staging bytes")
        if scenario == "recovery_orphan_final":
            class_row = conn.execute("SELECT id FROM classes ORDER BY id LIMIT 1").fetchone()
            if class_row is not None:
                target = settings.upload_dir / str(class_row["id"]) / "orphan-final.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"orphan final bytes")

        result = storage.recover_storage(conn, settings.upload_dir, settings.staging_dir)
        if not result.ok:
            raise StartupError(
                "无法清理无引用上传残留：" + "、".join(result.blocked)
                + "。请恢复上传目录的读写权限后重新启动。"
            )
        if scenario == "recovery_blocked":
            raise StartupError("注入：上传目录清理权限被阻止，禁止对外提供服务。")
        # 仍有 pending 任务不影响启动：对应资源已不可访问。
        storage.cleanup_once(conn, settings.upload_dir)
    finally:
        conn.close()


def create_app(
    settings: Settings | None = None,
    env: dict[str, str] | None = None,
    run_startup: bool = True,
) -> Flask:
    if settings is None and env is None:
        # 仅默认启动路径（app.py / gunicorn app:app）合并项目根 .env；
        # 显式传入 settings 或 env 的测试与脚本保持环境完全可控，不受本机 .env 影响。
        load_project_dotenv()
    if settings is None:
        settings = load_settings(env)
    if run_startup:
        prepare_storage_and_db(settings, env=env)

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder=None,  # 不提供任何公开静态目录
    )
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.cookie_secure,
        SESSION_COOKIE_PATH="/",
        SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=settings.max_content_bytes,
        JSON_SORT_KEYS=False,
    )
    app.extensions["campusclaw"] = {"settings": settings}
    # 仅供页面展示：把 UTC 入库时间转成本地可读格式，API 仍返回原始值。
    app.jinja_env.filters["localtime"] = timeutil.to_local_display

    app.teardown_appcontext(close_conn)

    from campusclaw.views.api_auth_views import bp as api_auth_bp
    from campusclaw.views.auth_views import bp as auth_bp
    from campusclaw.views.conversation_views import bp as conversation_bp
    from campusclaw.views.docs_views import bp as docs_bp
    from campusclaw.views.health_views import bp as health_bp
    from campusclaw.views.material_views import bp as materials_bp
    from campusclaw.views.mcp_views import bp as mcp_bp
    from campusclaw.views.page_views import bp as pages_bp
    from campusclaw.views.prompt_views import bp as prompt_bp
    from campusclaw.views.qa_views import bp as qa_bp
    from campusclaw.views.retrieval_views import bp as retrieval_bp
    from campusclaw.views.skill_views import bp as skill_bp
    from campusclaw.views.task_views import bp as task_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(materials_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(retrieval_bp)
    app.register_blueprint(prompt_bp)
    app.register_blueprint(skill_bp)
    app.register_blueprint(conversation_bp)
    app.register_blueprint(mcp_bp)
    app.register_blueprint(qa_bp)
    app.register_blueprint(task_bp)
    app.register_blueprint(docs_bp)

    register_error_handlers(app)
    # 覆盖 ApiError 处理器以支持受保护页面的 302 重定向。
    register_page_redirect(app)
    return app
