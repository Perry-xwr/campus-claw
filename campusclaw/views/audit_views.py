"""第 9 课 SEC-07：审计事件回查接口。

蓝图 ``audit_api``，只有教师可读——审计数据记录的是全体用户的行为，
对被记录者同样敏感，学生一律 403。

班级一律取自登录会话：教师只能看本班的拒绝记录，跨班不可见。
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from campusclaw import audit_db
from campusclaw import request_context as rc
from campusclaw.errors import ApiError, MESSAGES

bp = Blueprint("audit_api", __name__)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _require_teacher() -> dict:
    """读接口权限链：认证 → 仅教师。"""
    user = rc.require_api_auth()
    if user["role"] != "teacher":
        raise ApiError(403, "ROLE_FORBIDDEN", MESSAGES["ROLE_FORBIDDEN"])
    return user


@bp.get("/api/audit/events")
def list_audit_events():
    """按时间倒序回查本班审计事件；支持 status / actor / skill_id 过滤。"""
    user = _require_teacher()
    raw_limit = request.args.get("limit", str(DEFAULT_LIMIT))
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise ApiError(400, "INVALID_INPUT", "审计条数 limit 须为 1～200 的整数") from None
    if limit < 1:
        raise ApiError(400, "INVALID_INPUT", "审计条数 limit 须为 1～200 的整数")

    raw_status = request.args.get("status", "").strip()
    status: int | None = None
    if raw_status:
        try:
            status = int(raw_status)
        except ValueError:
            raise ApiError(400, "INVALID_INPUT", "状态码 status 须为整数") from None

    events = audit_db.list_events(
        rc.get_conn(),
        limit=min(limit, MAX_LIMIT),
        status=status,
        actor=request.args.get("actor", "").strip(),
        skill_id=request.args.get("skill_id", "").strip(),
    )
    class_id = int(user["class_id"])
    # 本班隔离：class_id 为空的记录（未认证尝试）只对同班可见性无法判定，
    # 因此教师查询统一按「本班或未归属」返回，不返回其他班级的记录。
    visible = [
        e for e in events if e["class_id"] is None or int(e["class_id"]) == class_id
    ]
    return jsonify({"events": visible, "count": len(visible)}), 200
