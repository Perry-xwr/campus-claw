"""技能 API：本班技能文件增删改查与文件上传；教师可写、师生可读。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from campusclaw import mcp_skill, request_context as rc, tutor_db
from campusclaw.errors import ApiError, MESSAGES

bp = Blueprint("skill_api", __name__)

#: 上传技能的字段名、允许的扩展名与大小上限。
SKILL_UPLOAD_FIELD = "file"
SKILL_FILE_EXTENSIONS = (".md", ".txt")
MAX_SKILL_FILE_BYTES = 64 * 1024


def _parse_id(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, "SKILL_ID_INVALID", MESSAGES["SKILL_ID_INVALID"]) from None
    if value < 1:
        raise ApiError(400, "SKILL_ID_INVALID", MESSAGES["SKILL_ID_INVALID"])
    return value


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_INPUT", MESSAGES["INVALID_INPUT"])
    return body


def _parse_source(body: dict) -> dict:
    source = body.get("source")
    if not isinstance(source, str):
        raise ApiError(400, "INVALID_INPUT", MESSAGES["INVALID_INPUT"])
    try:
        return tutor_db.parse_skill_source(source)
    except tutor_db.SkillFormatError as exc:
        raise ApiError(400, "SKILL_FILE_INVALID", str(exc)) from None


def _read_skill_file() -> str:
    """读取并解码技能文件：恰好一个 .md/.txt、非空、≤64KB、UTF-8 文本。

    只取文件内容，不信任文件名；解析与校验交给 ``parse_skill_source``。
    """
    files = request.files.getlist(SKILL_UPLOAD_FIELD)
    extra_fields = [key for key in request.files.keys() if key != SKILL_UPLOAD_FIELD]
    if extra_fields or len(files) != 1:
        raise ApiError(400, "INVALID_FILE", MESSAGES["INVALID_FILE"])
    uploaded = files[0]
    filename = (uploaded.filename or "").strip()
    if not filename.lower().endswith(SKILL_FILE_EXTENSIONS):
        raise ApiError(400, "UNSUPPORTED_FILE_TYPE", MESSAGES["UNSUPPORTED_FILE_TYPE"])
    data = uploaded.read()
    if not data:
        raise ApiError(400, "INVALID_FILE", MESSAGES["INVALID_FILE"])
    if len(data) > MAX_SKILL_FILE_BYTES:
        raise ApiError(400, "FILE_TOO_LARGE", "技能文件超过 64KB 上限")
    try:
        # utf-8-sig 兼容 Windows 记事本保存的 BOM 头。
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(400, "PARSE_FAILED", MESSAGES["PARSE_FAILED"]) from None


@bp.get("/api/skills")
def list_skills_api():
    user = rc.require_api_auth()
    skills = tutor_db.list_skills(rc.get_conn(), int(user["class_id"]))
    return jsonify({"skills": skills}), 200


@bp.post("/api/skills")
def create_skill_api():
    user = rc.require_write()
    parsed = _parse_source(_json_body())
    conn = rc.get_conn()
    class_id = int(user["class_id"])
    # 第 6 课：MCP 工具引用保存前四道校验，任一不过整份拒绝。
    mcp_skill.validate_tool_refs(conn, class_id, parsed["tools"])
    if tutor_db.skill_name_taken(conn, class_id, parsed["name"]):
        raise ApiError(400, "SKILL_NAME_EXISTS", MESSAGES["SKILL_NAME_EXISTS"])
    skill = tutor_db.create_skill(conn, class_id, parsed, int(user["user_id"]))
    return jsonify(skill), 201


@bp.post("/api/skills/upload")
def upload_skill_api():
    """上传技能文件（multipart，.md/.txt）并创建技能。

    与 ``POST /api/skills`` 共用同一套解析与校验：文件内容必须是合法的技能文件，
    MCP 工具引用同样过保存前四道校验；同名 400。只读取内容，不落盘、不信任文件名。
    """
    user = rc.require_write()
    rc.upload_identity_check(request.form)
    source = _read_skill_file()
    try:
        parsed = tutor_db.parse_skill_source(source)
    except tutor_db.SkillFormatError as exc:
        raise ApiError(400, "SKILL_FILE_INVALID", str(exc)) from None
    conn = rc.get_conn()
    class_id = int(user["class_id"])
    # 第 6 课：MCP 工具引用保存前四道校验，任一不过整份拒绝。
    mcp_skill.validate_tool_refs(conn, class_id, parsed["tools"])
    if tutor_db.skill_name_taken(conn, class_id, parsed["name"]):
        raise ApiError(400, "SKILL_NAME_EXISTS", MESSAGES["SKILL_NAME_EXISTS"])
    skill = tutor_db.create_skill(conn, class_id, parsed, int(user["user_id"]))
    return jsonify(skill), 201


@bp.put("/api/skills/<skill_id>")
def update_skill_api(skill_id: str):
    user = rc.require_write()
    skill_id_int = _parse_id(skill_id)
    parsed = _parse_source(_json_body())
    conn = rc.get_conn()
    class_id = int(user["class_id"])
    existing = tutor_db.get_skill(conn, class_id, skill_id_int)
    if existing is None:
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    # 第 6 课：MCP 工具引用保存前四道校验，任一不过整份拒绝。
    mcp_skill.validate_tool_refs(conn, class_id, parsed["tools"])
    if tutor_db.skill_name_taken(conn, class_id, parsed["name"], exclude_id=skill_id_int):
        raise ApiError(400, "SKILL_NAME_EXISTS", MESSAGES["SKILL_NAME_EXISTS"])
    skill = tutor_db.update_skill(conn, class_id, skill_id_int, parsed)
    return jsonify(skill), 200


@bp.delete("/api/skills/<skill_id>")
def delete_skill_api(skill_id: str):
    user = rc.require_write()
    skill_id_int = _parse_id(skill_id)
    # 跨班与不存在统一 404，与"没有这条数据"表现一致。
    if not tutor_db.delete_skill(rc.get_conn(), int(user["class_id"]), skill_id_int):
        raise ApiError(404, "NOT_FOUND", MESSAGES["NOT_FOUND"])
    return "", 204
