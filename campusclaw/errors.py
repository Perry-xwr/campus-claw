"""统一错误结构与错误处理器。

所有 JSON 错误统一为 ``{"error":{"code":...,"message":...}}``。
错误信息不得包含口令、哈希、SQL、异常堆栈、绝对路径或他班内容。
"""

from __future__ import annotations

from typing import Any

from flask import Flask, Response, jsonify
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """业务错误：携带固定 HTTP 状态码与错误码。"""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


# 对外统一提示，不区分账号是否存在（登录由 auth_views 直接给出“账号或密码错误”）
MESSAGES = {
    "AUTH_REQUIRED": "需要登录后访问",
    "ROLE_FORBIDDEN": "当前角色不允许执行该操作",
    "CSRF_INVALID": "请求令牌无效或缺失",
    "MATERIAL_NOT_FOUND": "材料不存在",
    "IDENTITY_FIELD_FORBIDDEN": "请求中包含不允许由客户端指定的身份字段",
    "INVALID_INPUT": "请求输入不完整或不合法",
    "INVALID_FILE": "必须提交恰好一个非空文件",
    "INVALID_TITLE": "标题长度须为 1～200 个字符且不含控制字符",
    "INVALID_FIELDS": "请求包含合同之外的字段",
    "FILE_TOO_LARGE": "文件超过大小上限",
    "UNSUPPORTED_FILE_TYPE": "仅支持 .txt 与 .md 文本文件",
    "PARSE_FAILED": "文件无法解析为 UTF-8 文本",
    "STORAGE_ERROR": "文件存储不可用，未保存任何数据",
    "DATABASE_ERROR": "数据库写入失败，未保存任何数据",
    "NOT_FOUND": "资源不存在",
    "METHOD_NOT_ALLOWED": "方法不被允许",
    "INTERNAL_ERROR": "服务器内部错误",
    "INVALID_CREDENTIALS": "账号或密码错误",
    "PROMPT_LENGTH": "提示词长度不正确",
    "SKILL_NAME_EXISTS": "技能名称已存在",
    "SKILL_ID_INVALID": "技能编号无法解析",
    "CONVERSATION_ID_INVALID": "会话编号无法解析",
    "QUESTION_TOO_SHORT": "问题至少需要 2 个字符",
    "QUESTION_TOO_LONG": "问题过长",
    "CONVERSATION_BODY": "请求必须是 JSON",
    "CHAT_UNAVAILABLE": "对话服务暂不可用",
    "TITLE_LENGTH": "会话标题长度不正确",
    "ANSWER_MODE_INVALID": "回答方式只能是 guide（引导）或 direct（直接回答）",
    # 第 6 课：MCP 与工具接入。
    "MCP_NAME_EXISTS": "本班已有同名 MCP 服务器",
    "MCP_INVALID_INPUT": "MCP 服务器名称或地址不合法",
    "MCP_ID_INVALID": "MCP 服务器编号无法解析",
    "MCP_CONNECT_FAILED": "无法连接该 MCP 服务器或获取工具清单失败，请检查地址与令牌",
    "MCP_SERVER_BUSY": "该服务器已有调用审计记录，为保证审计可追溯，不能删除",
    "MCP_TOOL_INVALID": "技能中的 MCP 工具引用不合法",
    "MCP_UNAVAILABLE": "MCP 服务暂不可用",
    # 班级答疑广场（小组项目扩展）。
    "QA_TITLE_INVALID": "标题长度须为 1～120 个字符",
    "QA_BODY_INVALID": "问题正文长度须为 1～5000 个字符",
    "QA_REPLY_INVALID": "回复长度须为 1～2000 个字符",
    "QA_QUESTION_CLOSED": "问题已关闭，不能继续回复或转人工",
    "QA_QUESTION_OPEN": "问题未关闭，无需重新打开",
    "QA_REPLY_NOT_IN_QUESTION": "该回复不属于当前问题",
    "QA_NOT_ACCEPTED": "当前问题尚未采纳任何回答",
    "QA_NOT_RESOLVED": "只有已采纳有效回答的问题才能生成 FAQ",
    "QA_FAQ_EXISTS": "该问题已有 FAQ",
    "QA_FAQ_REVOKED": "该 FAQ 已撤销",
    "QA_FAQ_PUBLISHED": "该 FAQ 已发布，无需重新发布",
    "QA_PAGE_INVALID": "分页或筛选参数不合法",
}


def raise_api(code: str, status: int, message: str | None = None) -> None:
    raise ApiError(status, code, message or MESSAGES.get(code, code))


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError) -> tuple[Response, int]:
        return jsonify(error_body(exc.code, exc.message)), exc.status

    @app.errorhandler(413)
    def _too_large(_exc: HTTPException) -> tuple[Response, int]:
        return jsonify(error_body("FILE_TOO_LARGE", MESSAGES["FILE_TOO_LARGE"])), 413

    @app.errorhandler(HTTPException)
    def _http_exception(exc: HTTPException) -> tuple[Response, int]:
        status = exc.code or 500
        if status == 404:
            code = "NOT_FOUND"
        elif status == 405:
            code = "METHOD_NOT_ALLOWED"
        elif status == 415:
            code = "UNSUPPORTED_FILE_TYPE"
        elif status == 400:
            code = "INVALID_INPUT"
        else:
            code = "NOT_FOUND" if status < 500 else "INTERNAL_ERROR"
        return jsonify(error_body(code, MESSAGES.get(code, code))), status

    @app.errorhandler(Exception)
    def _unexpected(_exc: Exception) -> tuple[Response, int]:
        app.logger.exception("unhandled server error")
        return jsonify(error_body("INTERNAL_ERROR", MESSAGES["INTERNAL_ERROR"])), 500
