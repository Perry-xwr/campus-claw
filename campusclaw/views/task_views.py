"""第 8 课：异步批改的提交契约与只读状态接口。

POST /api/submissions 只承诺「已接收」：202 + task_id + status_url，响应体不含评分。
GET  /api/tasks/<task_id> 只读：连续查询不会触发执行，也不会增加 attempts。
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from campusclaw import request_context as rc, task_db
from campusclaw.errors import ApiError

bp = Blueprint("task_api", __name__)

ALLOWED_FIELDS = frozenset({"assignment_ref", "content"})


@bp.post("/api/submissions")
def submit_api():
    user = rc.require_write_any()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "TASK_INPUT_INVALID", "请求必须是 JSON 对象")
    rc.reject_identity_fields(body)
    if set(body) - ALLOWED_FIELDS:
        raise ApiError(400, "TASK_INPUT_INVALID", "请求包含合同之外的字段")
    assignment_ref = body.get("assignment_ref")
    content = body.get("content")
    if (not isinstance(assignment_ref, str)
            or not 1 <= len(assignment_ref.strip()) <= 120):
        raise ApiError(400, "TASK_INPUT_INVALID", "作业标识长度须为 1～120 个字符")
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 5000:
        raise ApiError(400, "TASK_INPUT_INVALID", "作答内容长度须为 1～5000 个字符")

    task = task_db.submit(
        rc.get_conn(),
        class_id=int(user["class_id"]),
        user_id=int(user["user_id"]),
        assignment_ref=assignment_ref.strip(),
        content=content,
    )
    # 202 Accepted：调用方凭 task_id 之后来取结果，这里绝不能带分数。
    return jsonify(task), 202


@bp.get("/api/tasks/<task_id>")
def task_status_api(task_id: str):
    user = rc.require_api_auth()
    payload = task_db.status_for(rc.get_conn(), task_id, int(user["class_id"]))
    if payload is None:
        raise ApiError(404, "TASK_NOT_FOUND", "任务不存在")
    return jsonify(payload), 200


@bp.get("/api/tasks/observations")
def task_observations_api():
    """队列观测：积压、死信、重试次数、平均执行耗时（判据二/三的证据来源）。"""
    user = rc.require_api_auth()
    if user["role"] != "teacher":
        raise ApiError(403, "ROLE_FORBIDDEN", "当前角色不允许执行该操作")
    return jsonify(task_db.observations(rc.get_conn(), int(user["class_id"]))), 200
