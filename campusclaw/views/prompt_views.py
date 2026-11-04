"""提示词 API：每班一条，教师可写、师生可读。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from campusclaw import request_context as rc, tutor_db
from campusclaw.errors import ApiError, MESSAGES

bp = Blueprint("prompt_api", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_INPUT", MESSAGES["INVALID_INPUT"])
    return body


@bp.get("/api/prompt")
def get_prompt_api():
    user = rc.require_api_auth()
    row = tutor_db.get_prompt(rc.get_conn(), int(user["class_id"]))
    return jsonify({
        "body": row["body"] if row else "",
        "updated_at": row["updated_at"] if row else None,
    }), 200


@bp.put("/api/prompt")
def save_prompt_api():
    user = rc.require_write()
    body = _json_body()
    value = body.get("body")
    if not isinstance(value, str):
        raise ApiError(400, "PROMPT_LENGTH", MESSAGES["PROMPT_LENGTH"])
    if not 1 <= len(value.strip()) <= tutor_db.MAX_PROMPT_BODY:
        raise ApiError(400, "PROMPT_LENGTH", MESSAGES["PROMPT_LENGTH"])
    saved = tutor_db.save_prompt(
        rc.get_conn(), int(user["class_id"]), value.strip(), int(user["user_id"])
    )
    return jsonify(saved), 200
