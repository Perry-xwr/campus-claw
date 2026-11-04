"""班级答疑广场：问题、回复、状态机、AI 辅助、FAQ 与统计。

权限收口：本蓝图所有路由必须以 ``@qa_login``（本班成员）或 ``@qa_teacher``
（仅教师）开头。既有代码全库无 ``before_request``，靠视图显式调用 ``require_*``；
新模块接口较多，用装饰器保证不遗漏，同时不改动既有视图与全局钩子。

隔离约定：跨班与不存在一律返回同一个 404 ``NOT_FOUND``，与既有材料/会话接口一致。
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Iterator

from flask import (
    Blueprint,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)

from campusclaw import db as dbmod
from campusclaw import (
    qa_db,
    qa_faq_material,
    request_context as rc,
    retrieval,
    tutor,
    tutor_db,
)
from campusclaw.errors import ApiError, MESSAGES, raise_api
from campusclaw.retrieval_config import RetrievalConfig

logger = logging.getLogger(__name__)

bp = Blueprint("qa", __name__)

SEARCH_LIMIT = 4
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
AI_NOTICE = "AI 辅助生成，仅供参考"


# ---------------------------------------------------------------------------
# 装饰器：认证 → 角色 → CSRF
# ---------------------------------------------------------------------------

def qa_login(view):
    """已登录的本班成员。写方法要求 CSRF（Bearer 请求按既有约定豁免）。"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        user = rc.require_api_auth()
        rc.reject_identity_fields(request.get_json(silent=True) if request.is_json else None)
        if request.method in WRITE_METHODS:
            rc.require_csrf()
        return view(user, *args, **kwargs)

    return wrapper


def qa_teacher(view):
    """仅教师。角色判定先于 CSRF，与既有 ``require_write`` 的顺序一致。"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        user = rc.require_api_auth()
        if user["role"] != "teacher":
            raise ApiError(403, "ROLE_FORBIDDEN", MESSAGES["ROLE_FORBIDDEN"])
        rc.reject_identity_fields(request.get_json(silent=True) if request.is_json else None)
        if request.method in WRITE_METHODS:
            rc.require_csrf()
        return view(user, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------

def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_INPUT", MESSAGES["INVALID_INPUT"])
    return body


def _parse_id(raw: str) -> int:
    """非法格式与不存在同码：一律 404。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise_api("NOT_FOUND", 404)
    if value <= 0:
        raise_api("NOT_FOUND", 404)
    return value


def _text(value: Any, *, maximum: int, code: str) -> str:
    if not isinstance(value, str):
        raise_api(code, 400)
    stripped = value.strip()
    if not 1 <= len(stripped) <= maximum:
        raise_api(code, 400)
    return stripped


def _int_arg(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise_api("QA_PAGE_INVALID", 400)
    if value < minimum:
        raise_api("QA_PAGE_INVALID", 400)
    return min(value, maximum)


def _class_user(user: dict) -> tuple[int, int]:
    return int(user["class_id"]), int(user["user_id"])


def _not_found() -> None:
    raise_api("NOT_FOUND", 404)


# ---------------------------------------------------------------------------
# 问题与回复
# ---------------------------------------------------------------------------

@bp.get("/api/qa/questions")
@qa_login
def list_questions_api(user):
    class_id, _ = _class_user(user)
    status_raw = (request.args.get("status") or "").strip()
    statuses: list[str] | None = None
    if status_raw:
        statuses = [item.strip().upper() for item in status_raw.split(",") if item.strip()]
        if not statuses or any(item not in qa_db.STATUSES for item in statuses):
            raise_api("QA_PAGE_INVALID", 400)
    sort = (request.args.get("sort") or "new").strip()
    if sort not in qa_db.SORT_MODES:
        raise_api("QA_PAGE_INVALID", 400)
    page = _int_arg("page", 1, minimum=1, maximum=10**6)
    size = _int_arg("size", qa_db.DEFAULT_PAGE_SIZE, minimum=1, maximum=qa_db.MAX_PAGE_SIZE)
    handoff_only = request.args.get("handoff") == "1"
    unresolved_only = request.args.get("unresolved") == "1"

    payload = qa_db.list_questions(
        rc.get_conn(),
        class_id,
        statuses=statuses,
        sort=sort,
        page=page,
        size=size,
        handoff_only=handoff_only,
        unresolved_only=unresolved_only,
    )
    return jsonify(payload), 200


@bp.post("/api/qa/questions")
@qa_login
def create_question_api(user):
    class_id, user_id = _class_user(user)
    body = _json_body()
    title = _text(body.get("title"), maximum=qa_db.MAX_TITLE, code="QA_TITLE_INVALID")
    content = _text(body.get("body"), maximum=qa_db.MAX_BODY, code="QA_BODY_INVALID")
    question = qa_db.create_question(rc.get_conn(), class_id, user_id, title, content)
    return jsonify(question), 201


@bp.get("/api/qa/questions/<question_id>")
@qa_login
def question_detail_api(user, question_id: str):
    class_id, _ = _class_user(user)
    question_id_int = _parse_id(question_id)
    conn = rc.get_conn()
    question = qa_db.get_question(conn, question_id_int, class_id)
    if question is None:
        _not_found()
    return (
        jsonify(
            {
                "question": question,
                "replies": qa_db.list_replies(conn, question_id_int),
                "ai_answer": qa_db.latest_ai_answer(conn, question_id_int, class_id),
                "ai_answer_count": qa_db.ai_answer_count(conn, question_id_int),
                "faq": qa_db.faq_for_question(conn, question_id_int, class_id),
            }
        ),
        200,
    )


@bp.post("/api/qa/questions/<question_id>/replies")
@qa_login
def create_reply_api(user, question_id: str):
    class_id, user_id = _class_user(user)
    question_id_int = _parse_id(question_id)
    body = _json_body()
    content = _text(body.get("body"), maximum=qa_db.MAX_REPLY, code="QA_REPLY_INVALID")
    conn = rc.get_conn()
    if qa_db.get_question(conn, question_id_int, class_id) is None:
        _not_found()
    try:
        reply = qa_db.add_reply(
            conn,
            question_id_int,
            class_id,
            user_id,
            content,
            is_teacher=user["role"] == "teacher",
        )
    except qa_db.QuestionClosed:
        raise_api("QA_QUESTION_CLOSED", 409)
    except qa_db.ReplyNotFound:
        _not_found()
    return jsonify(reply), 201


@bp.post("/api/qa/questions/<question_id>/handoff")
@qa_login
def handoff_api(user, question_id: str):
    class_id, user_id = _class_user(user)
    question_id_int = _parse_id(question_id)
    try:
        question = qa_db.mark_handoff(rc.get_conn(), question_id_int, class_id, user_id)
    except qa_db.QuestionClosed:
        raise_api("QA_QUESTION_CLOSED", 409)
    if question is None:
        _not_found()
    return jsonify(question), 200


@bp.post("/api/qa/questions/<question_id>/accept")
@qa_teacher
def accept_api(user, question_id: str):
    class_id, _ = _class_user(user)
    question_id_int = _parse_id(question_id)
    body = _json_body()
    try:
        reply_id = int(body.get("reply_id"))
    except (TypeError, ValueError):
        raise_api("QA_REPLY_NOT_IN_QUESTION", 400)
    try:
        question = qa_db.accept_reply(rc.get_conn(), question_id_int, class_id, reply_id)
    except qa_db.ReplyNotFound:
        raise_api("QA_REPLY_NOT_IN_QUESTION", 400)
    if question is None:
        _not_found()
    return jsonify(question), 200


@bp.delete("/api/qa/questions/<question_id>/accept")
@qa_teacher
def unaccept_api(user, question_id: str):
    class_id, _ = _class_user(user)
    question_id_int = _parse_id(question_id)
    try:
        question = qa_db.unaccept(rc.get_conn(), question_id_int, class_id)
    except qa_db.NotAccepted:
        raise_api("QA_NOT_ACCEPTED", 400)
    if question is None:
        _not_found()
    return jsonify(question), 200


@bp.post("/api/qa/questions/<question_id>/close")
@qa_teacher
def close_api(user, question_id: str):
    class_id, _ = _class_user(user)
    question_id_int = _parse_id(question_id)
    try:
        question = qa_db.close_question(rc.get_conn(), question_id_int, class_id)
    except qa_db.AlreadyClosed:
        raise_api("QA_QUESTION_CLOSED", 409)
    if question is None:
        _not_found()
    return jsonify(question), 200


@bp.post("/api/qa/questions/<question_id>/reopen")
@qa_teacher
def reopen_api(user, question_id: str):
    class_id, _ = _class_user(user)
    question_id_int = _parse_id(question_id)
    try:
        question = qa_db.reopen_question(rc.get_conn(), question_id_int, class_id)
    except qa_db.NotClosed:
        raise_api("QA_QUESTION_OPEN", 409)
    if question is None:
        _not_found()
    return jsonify(question), 200


# ---------------------------------------------------------------------------
# AI 辅助答疑（复用检索 + 流式生成）
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict[str, Any]) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _retrieve_for_question(
    conn, question_text: str, class_id: int
) -> tuple[list[dict], str]:
    """混合优先、关键词回退；与解题助手同一策略，不新增检索分支。"""
    config = RetrievalConfig.from_env()
    if config.embedding_ready:
        try:
            hits = retrieval.search(
                conn, question_text, "hybrid", class_id, SEARCH_LIMIT, config
            )
            return hits, "hybrid"
        except retrieval.RetrievalUnavailable:
            logger.info("qa: vector retrieval unavailable; falling back to keyword")
        except Exception:
            logger.exception("qa: hybrid retrieval failed; falling back to keyword")
    return retrieval.keyword_search(conn, question_text, class_id, SEARCH_LIMIT), "keyword"


def _ai_pipeline(
    question: dict,
    user_ctx: dict,
    class_id: int,
    hits: list[dict],
    retrieval_mode: str,
) -> Iterator[str]:
    """SSE 生成器：meta → delta* → done；流中失败补 error，HTTP 保持 200。"""
    conn = rc.get_conn()
    question_id = int(question["id"])
    prompt_row = tutor_db.get_prompt(conn, class_id)
    prompt_body = prompt_row["body"] if prompt_row else tutor_db.DEFAULT_PROMPT
    query = f"{question['title']}\n{question['body']}".strip()
    skill = tutor_db.select_skill(conn, class_id, query)
    citations = tutor.public_citations(hits)
    config = RetrievalConfig.from_env()

    meta: dict[str, Any] = {
        "status": "ok" if hits else "no_hits",
        "citations": citations,
        "retrieval_mode": retrieval_mode,
        "ai_generated": True,
        "notice": AI_NOTICE,
    }
    yield _sse("meta", meta)

    parts: list[str] = []
    try:
        for text in tutor.stream_answer(
            prompt_body,
            skill,
            hits,
            query,
            user_ctx,
            config,
            history=None,
            tool_results=None,
            answer_mode="direct",
        ):
            parts.append(text)
            yield _sse("delta", {"text": text})
    except Exception:
        logger.exception("qa: ai answer stream failed for question %s", question_id)
        yield _sse("error", {"error": MESSAGES["CHAT_UNAVAILABLE"]})
        return

    answer = "".join(parts).strip()
    status = "ok" if hits else "no_hits"
    settings = rc.get_settings()
    writer = dbmod.connect(settings.db_path)
    try:
        if answer:
            qa_db.add_ai_answer(
                writer,
                question_id,
                class_id,
                int(user_ctx["user_id"]),
                answer,
                citations,
                status,
                retrieval_mode,
            )
            answer_id = qa_db.latest_ai_answer(writer, question_id, class_id)
        else:
            answer_id = None
    finally:
        writer.close()
    yield _sse(
        "done",
        {"answer_id": (answer_id or {}).get("id"), "status": status, "notice": AI_NOTICE},
    )


@bp.post("/api/qa/questions/<question_id>/ai-answer")
@qa_login
def ai_answer_api(user, question_id: str):
    class_id, user_id = _class_user(user)
    question_id_int = _parse_id(question_id)
    conn = rc.get_conn()
    question = qa_db.get_question(conn, question_id_int, class_id)
    if question is None:
        _not_found()
    if question["status"] == "CLOSED":
        raise_api("QA_QUESTION_CLOSED", 409)

    query = f"{question['title']}\n{question['body']}".strip()
    try:
        hits, retrieval_mode = _retrieve_for_question(conn, query, class_id)
    except Exception as exc:
        logger.exception("qa: retrieval failed for question %s", question_id)
        raise ApiError(503, "RETRIEVAL_UNAVAILABLE", "检索服务暂不可用") from exc

    user_ctx = {
        "user_id": user_id,
        "username": user["username"],
        "role": user["role"],
        "class_id": class_id,
        "class_name": user.get("class_name", ""),
    }
    stream = stream_with_context(
        _ai_pipeline(question, user_ctx, class_id, hits, retrieval_mode)
    )
    return Response(
        stream,
        mimetype="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------

@bp.get("/api/qa/questions/<question_id>/faq-draft")
@qa_teacher
def faq_draft_api(user, question_id: str):
    class_id, _ = _class_user(user)
    question_id_int = _parse_id(question_id)
    conn = rc.get_conn()
    draft = qa_db.faq_draft(conn, question_id_int, class_id)
    if draft is None:
        if qa_db.get_question(conn, question_id_int, class_id) is None:
            _not_found()
        raise_api("QA_NOT_RESOLVED", 400)
    return jsonify(draft), 200


@bp.get("/api/qa/faqs")
@qa_login
def list_faqs_api(user):
    class_id, _ = _class_user(user)
    include_revoked = request.args.get("include_revoked") == "1" and user["role"] == "teacher"
    return jsonify({"items": qa_db.list_faqs(rc.get_conn(), class_id, include_revoked)}), 200


@bp.get("/api/qa/faqs/<faq_id>")
@qa_login
def faq_detail_api(user, faq_id: str):
    class_id, _ = _class_user(user)
    faq_id_int = _parse_id(faq_id)
    faq = qa_db.get_faq(
        rc.get_conn(), faq_id_int, class_id, include_revoked=user["role"] == "teacher"
    )
    if faq is None:
        _not_found()
    return jsonify(faq), 200


def _rebuild_faq_material(class_id: int, teacher_id: int) -> None:
    """FAQ 变更后重建汇总材料；失败只记日志，不影响 FAQ 本身。"""
    conn = rc.get_conn()
    qa_faq_material.rebuild(conn, rc.get_settings(), class_id, teacher_id)


@bp.post("/api/qa/faqs")
@qa_teacher
def create_faq_api(user):
    class_id, user_id = _class_user(user)
    body = _json_body()
    try:
        question_id = int(body.get("question_id"))
    except (TypeError, ValueError):
        raise_api("QA_NOT_RESOLVED", 400)
    question_text = _text(
        body.get("question_text"), maximum=qa_db.MAX_FAQ_QUESTION, code="QA_BODY_INVALID"
    )
    answer_text = _text(
        body.get("answer_text"), maximum=qa_db.MAX_FAQ_ANSWER, code="QA_BODY_INVALID"
    )
    conn = rc.get_conn()
    question = qa_db.get_question(conn, question_id, class_id)
    if question is None:
        _not_found()
    if question["accepted_reply_id"] is None:
        raise_api("QA_NOT_RESOLVED", 400)
    try:
        faq_id = qa_db.create_faq(
            conn,
            class_id,
            question_id,
            question["accepted_reply_id"],
            question_text,
            answer_text,
            user_id,
        )
    except qa_db.FaqExists:
        raise_api("QA_FAQ_EXISTS", 409)
    _rebuild_faq_material(class_id, user_id)
    return jsonify(qa_db.get_faq(conn, faq_id, class_id, include_revoked=True)), 201


@bp.put("/api/qa/faqs/<faq_id>")
@qa_teacher
def update_faq_api(user, faq_id: str):
    class_id, user_id = _class_user(user)
    faq_id_int = _parse_id(faq_id)
    body = _json_body()
    question_text = _text(
        body.get("question_text"), maximum=qa_db.MAX_FAQ_QUESTION, code="QA_BODY_INVALID"
    )
    answer_text = _text(
        body.get("answer_text"), maximum=qa_db.MAX_FAQ_ANSWER, code="QA_BODY_INVALID"
    )
    faq = qa_db.update_faq(rc.get_conn(), faq_id_int, class_id, question_text, answer_text)
    if faq is None:
        _not_found()
    _rebuild_faq_material(class_id, user_id)
    return jsonify(faq), 200


@bp.delete("/api/qa/faqs/<faq_id>")
@qa_teacher
def revoke_faq_api(user, faq_id: str):
    class_id, user_id = _class_user(user)
    faq_id_int = _parse_id(faq_id)
    try:
        result = qa_db.revoke_faq(rc.get_conn(), faq_id_int, class_id)
    except qa_db.FaqRevoked:
        raise_api("QA_FAQ_REVOKED", 409)
    if result is None:
        _not_found()
    _rebuild_faq_material(class_id, user_id)
    return "", 204


@bp.post("/api/qa/faqs/<faq_id>/republish")
@qa_teacher
def republish_faq_api(user, faq_id: str):
    class_id, user_id = _class_user(user)
    faq_id_int = _parse_id(faq_id)
    try:
        result = qa_db.republish_faq(rc.get_conn(), faq_id_int, class_id)
    except qa_db.FaqPublished:
        raise_api("QA_FAQ_PUBLISHED", 409)
    if result is None:
        _not_found()
    _rebuild_faq_material(class_id, user_id)
    return jsonify(qa_db.get_faq(rc.get_conn(), faq_id_int, class_id, True)), 200


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

@bp.get("/api/qa/stats")
@qa_teacher
def stats_api(user):
    class_id, _ = _class_user(user)
    return jsonify(qa_db.stats(rc.get_conn(), class_id)), 200


# ---------------------------------------------------------------------------
# 页面（服务端渲染）
# ---------------------------------------------------------------------------

@bp.get("/qa")
def qa_list_page():
    user = rc.require_page_auth()
    class_id = int(user["class_id"])
    conn = rc.get_conn()
    status_raw = (request.args.get("status") or "").strip().upper()
    statuses = [status_raw] if status_raw in qa_db.STATUSES else None
    sort = request.args.get("sort") if request.args.get("sort") in qa_db.SORT_MODES else "new"
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    payload = qa_db.list_questions(
        conn, class_id, statuses=statuses, sort=sort, page=page
    )
    return render_template(
        "qa_list.html",
        user=user,
        csrf_token=rc.ensure_csrf_token(),
        payload=payload,
        summary=qa_db.stats(conn, class_id),
        status_filter=status_raw,
        sort=sort,
    )


@bp.get("/qa/questions/<question_id>")
def qa_detail_page(question_id: str):
    user = rc.require_page_auth()
    class_id = int(user["class_id"])
    conn = rc.get_conn()
    try:
        question_id_int = int(question_id)
    except ValueError:
        raise_api("NOT_FOUND", 404)
    question = qa_db.get_question(conn, question_id_int, class_id)
    if question is None:
        raise_api("NOT_FOUND", 404)
    return render_template(
        "qa_detail.html",
        user=user,
        csrf_token=rc.ensure_csrf_token(),
        question=question,
        replies=qa_db.list_replies(conn, question_id_int),
        ai_answer=qa_db.latest_ai_answer(conn, question_id_int, class_id),
        faq=qa_db.faq_for_question(conn, question_id_int, class_id),
    )


@bp.get("/qa/faq")
def qa_faq_page():
    user = rc.require_page_auth()
    class_id = int(user["class_id"])
    include_revoked = user["role"] == "teacher" and request.args.get("all") == "1"
    return render_template(
        "qa_faq.html",
        user=user,
        csrf_token=rc.ensure_csrf_token(),
        faqs=qa_db.list_faqs(rc.get_conn(), class_id, include_revoked),
        include_revoked=include_revoked,
    )


@bp.get("/qa/stats")
def qa_stats_page():
    user = rc.require_page_auth()
    if user["role"] != "teacher":
        return redirect(url_for("qa.qa_list_page"))
    return render_template(
        "qa_stats.html",
        user=user,
        csrf_token=rc.ensure_csrf_token(),
        stats=qa_db.stats(rc.get_conn(), int(user["class_id"])),
    )
