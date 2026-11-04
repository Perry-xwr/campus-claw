"""会话 API：新建会话、连续追问、SSE 流式回答。"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from flask import Blueprint, Response, jsonify, request, stream_with_context

from campusclaw import db as dbmod, mcp_skill, retrieval, tutor, tutor_db
from campusclaw import request_context as rc
from campusclaw.errors import ApiError, MESSAGES
from campusclaw.retrieval_config import RetrievalConfig

logger = logging.getLogger(__name__)

bp = Blueprint("conversation_api", __name__)

SEARCH_LIMIT = 4
HISTORY_LIMIT = 6


def _parse_conversation_id(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError(
            400, "CONVERSATION_ID_INVALID", MESSAGES["CONVERSATION_ID_INVALID"]
        ) from None
    if value < 1:
        raise ApiError(400, "CONVERSATION_ID_INVALID", MESSAGES["CONVERSATION_ID_INVALID"])
    return value


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "CONVERSATION_BODY", MESSAGES["CONVERSATION_BODY"])
    return body


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@bp.get("/api/conversations")
def list_conversations_api():
    user = rc.require_api_auth()
    conversations = tutor_db.list_conversations(rc.get_conn(), int(user["user_id"]))
    return jsonify({"conversations": conversations}), 200


@bp.post("/api/conversations")
def create_conversation_api():
    user = rc.require_write_any()
    body = _json_body()
    title = body.get("title", "新的提问")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= tutor_db.MAX_TITLE:
        raise ApiError(400, "TITLE_LENGTH", MESSAGES["TITLE_LENGTH"])
    conversation = tutor_db.create_conversation(
        rc.get_conn(), int(user["user_id"]), int(user["class_id"]), title.strip()
    )
    return jsonify(conversation), 201


@bp.get("/api/conversations/<conversation_id>")
def get_conversation_api(conversation_id: str):
    user = rc.require_api_auth()
    conversation_id_int = _parse_conversation_id(conversation_id)
    conversation = tutor_db.get_conversation(
        rc.get_conn(), int(user["user_id"]), conversation_id_int
    )
    # 别人的会话、跨班会话与不存在返回同一个 404。
    if conversation is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    messages = tutor_db.list_messages(rc.get_conn(), conversation_id_int)
    return jsonify({"conversation": conversation, "messages": messages}), 200


ANSWER_MODES = ("guide", "direct")


def _retrieve_for_answer(conn, question: str, class_id: int) -> tuple[list[dict], str]:
    """优先混合检索（关键词 + 向量），嵌入未配置或向量库不可用时回退关键词。

    返回 ``(hits, mode)``；mode 会写进 SSE ``meta``，便于确认本次走了哪条链路。
    """
    config = RetrievalConfig.from_env()
    if config.embedding_ready:
        try:
            hits = retrieval.search(conn, question, "hybrid", class_id, SEARCH_LIMIT, config)
            return hits, "hybrid"
        except retrieval.RetrievalUnavailable:
            logger.info("vector retrieval unavailable; falling back to keyword")
        except Exception:
            logger.exception("hybrid retrieval failed; falling back to keyword")
    hits = retrieval.keyword_search(conn, question, class_id, SEARCH_LIMIT)
    return hits, "keyword"


def _run_pipeline(
    question: str,
    user: dict,
    conversation_id: int,
    hits: list[dict],
    answer_mode: str = "guide",
    retrieval_mode: str = "keyword",
):
    """SSE 生成器：meta → delta* → done；流中失败补 error，HTTP 保持 200。"""
    conn = rc.get_conn()
    class_id = int(user["class_id"])
    user_id = int(user["user_id"])
    prompt_row = tutor_db.get_prompt(conn, class_id)
    prompt_body = prompt_row["body"] if prompt_row else tutor_db.DEFAULT_PROMPT
    skill = tutor_db.select_skill(conn, class_id, question)
    citations = tutor.public_citations(hits)
    # 第 6 课：选技能后、推 meta 前，按技能工具白名单确定性调用 MCP 工具。
    # run_skill_tools 整体有兜底，任何工具失败都不阻断检索与流式回答。
    tool_calls = mcp_skill.run_skill_tools(
        conn, class_id, skill, question, user_id, conversation_id
    )
    # 历史取当前问题之前的消息：用户消息在进入管道前已落库，
    # 若把刚入库的当前问题也算作历史，同一问题会在提示词里出现两次。
    prior = tutor_db.list_messages(conn, conversation_id)
    if prior and prior[-1]["role"] == "user":
        prior = prior[:-1]
    history = [
        {"role": item["role"], "content": item["content"]}
        for item in prior[-HISTORY_LIMIT:]
    ]
    config = RetrievalConfig.from_env()

    meta: dict[str, Any] = {
        "status": "ok" if hits else "no_hits",
        "citations": citations,
        "skill_name": skill["name"] if skill else "",
        "prompt_saved": bool(prompt_row),
        "answer_mode": answer_mode,
        "retrieval_mode": retrieval_mode,
    }
    # 仅当本次确有调用才带 tool_calls；无调用整个键不出现（而非空数组）。
    if tool_calls:
        meta["tool_calls"] = tool_calls
    yield _sse("meta", meta)

    # 工具返回（仅 ref/text）作为数据拼进用户消息；无调用传 None。
    tool_results = [{"ref": item["ref"], "text": item["text"]} for item in tool_calls]

    parts: list[str] = []
    try:
        for text in tutor.stream_answer(
            prompt_body, skill, hits, question, user, config, history,
            tool_results or None, answer_mode,
        ):
            parts.append(text)
            yield _sse("delta", {"text": text})
    except Exception:
        # 流已开始：补 error 事件，不写半截 assistant 消息。
        logger.exception("tutor stream failed for conversation %s", conversation_id)
        yield _sse("error", {"error": MESSAGES["CHAT_UNAVAILABLE"]})
        return

    answer = "".join(parts).strip()
    settings = rc.get_settings()
    writer = dbmod.connect(settings.db_path)
    try:
        message_id = tutor_db.add_message(
            writer,
            conversation_id,
            "assistant",
            answer,
            citations=citations,
            skill=skill,
            tool_calls=tool_calls or None,
        )
        tutor_db.touch_conversation(writer, conversation_id)
    finally:
        writer.close()
    yield _sse("done", {"message_id": message_id})


@bp.post("/api/conversations/<conversation_id>/messages")
def post_message_api(conversation_id: str):
    user = rc.require_write_any()
    conversation_id_int = _parse_conversation_id(conversation_id)
    body = _json_body()
    content = body.get("content")
    if not isinstance(content, str):
        raise ApiError(400, "QUESTION_TOO_SHORT", MESSAGES["QUESTION_TOO_SHORT"])
    question = content.strip()
    if len(question) < tutor_db.MIN_QUESTION:
        raise ApiError(400, "QUESTION_TOO_SHORT", MESSAGES["QUESTION_TOO_SHORT"])
    if len(question) > tutor_db.MAX_QUESTION:
        raise ApiError(400, "QUESTION_TOO_LONG", MESSAGES["QUESTION_TOO_LONG"])

    # 回答方式：guide（默认，只给思路）/ direct（正面回答，给结论与数量）。
    answer_mode = body.get("mode", "guide")
    if answer_mode not in ANSWER_MODES:
        raise ApiError(400, "ANSWER_MODE_INVALID", MESSAGES["ANSWER_MODE_INVALID"])

    conn = rc.get_conn()
    conversation = tutor_db.get_conversation(
        conn, int(user["user_id"]), conversation_id_int
    )
    if conversation is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])

    # 用户消息先落库，再开始检索与生成。
    tutor_db.add_message(conn, conversation_id_int, "user", question)

    # 回答前先检索本班知识库：有嵌入配置时走混合检索，否则回退关键词。
    try:
        hits, retrieval_mode = _retrieve_for_answer(
            conn, question, int(user["class_id"])
        )
    except Exception as exc:
        logger.exception("tutor retrieval failed for conversation %s", conversation_id)
        raise ApiError(
            503, "RETRIEVAL_UNAVAILABLE", "检索服务暂不可用"
        ) from exc

    user_ctx = {
        "user_id": int(user["user_id"]),
        "username": user["username"],
        "role": user["role"],
        "class_id": int(user["class_id"]),
        "class_name": user.get("class_name", ""),
    }
    stream: Iterator[str] = stream_with_context(
        _run_pipeline(
            question, user_ctx, conversation_id_int, hits, answer_mode, retrieval_mode
        )
    )
    return Response(
        stream,
        mimetype="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.delete("/api/conversations/<conversation_id>")
def delete_conversation_api(conversation_id: str):
    """删除本人的会话及其消息；MCP 审计行保留，仅把 conversation_id 置空。

    跨班 / 他人的会话与不存在统一 404。
    """
    user = rc.require_write_any()
    conversation_id_int = _parse_conversation_id(conversation_id)
    if not tutor_db.delete_conversation(
        rc.get_conn(), int(user["user_id"]), conversation_id_int
    ):
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    return "", 204
