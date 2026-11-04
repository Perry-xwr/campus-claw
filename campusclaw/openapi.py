"""OpenAPI 3 文档：CampusClaw 全部 API 的路径、入参出参、错误码与登录要求。

文档与实现同仓维护；``GET /openapi.json`` 直接返回本结构，
``GET /swagger/index.html`` 提供可试调的 Swagger UI。
"""

from __future__ import annotations

import copy

BEARER_DESC = (
    "Bearer 访问令牌。POST /api/login 成功后返回的 token 原样填入，"
    "格式为 Authorization: Bearer <token>。令牌即服务端会话，登出或过期后失效。"
)

_ERROR_BODY = {
    "description": "错误响应体",
    "content": {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/ErrorBody"},
            "example": {"error": {"code": "NOT_FOUND", "message": "资源不存在"}},
        }
    },
}


def _json_schema(properties: dict, required: list[str] | None = None) -> dict:
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _bearer_security() -> list[dict]:
    return [{"bearerAuth": []}]


def _id_path(name: str, description: str) -> dict:
    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": {"type": "integer", "minimum": 1},
    }


def _auth_header() -> dict:
    return {
        "name": "Authorization",
        "in": "header",
        "required": True,
        "description": BEARER_DESC,
        "schema": {"type": "string"},
        "example": "Bearer <token>",
    }


def build_openapi() -> dict:
    """返回完整 OpenAPI 3.0.3 文档（dict）。"""
    doc: dict = {
        "openapi": "3.0.3",
        "info": {
            "title": "CampusClaw API",
            "version": "1.0.0",
            "description": (
                "CampusClaw 班级教学材料管理与解题助手 API。\n\n"
                "认证：除 /health、/openapi.json 与 /swagger 外，所有 /api/ 接口都需要 "
                "Authorization: Bearer <token>（POST /api/login 签发）；"
                "令牌即服务端会话，登出即吊销。网页 Cookie 会话同样可用，"
                "但 Bearer 写请求不要求 X-CSRF-Token。\n\n"
                "班级隔离：服务端从登录会话读取用户与班级，请求正文中的 class_id/role/"
                "user_id 等身份字段一律忽略；跨班访问与“没有这条数据”表现一致（统一 404）。"
            ),
        },
        "servers": [{"url": "/", "description": "当前服务器"}],
        "tags": [
            {"name": "auth", "description": "登录、登出与当前身份"},
            {"name": "materials", "description": "本班材料管理与下载"},
            {"name": "search", "description": "本班检索与单次问答"},
            {"name": "prompt", "description": "本班提示词（教师可写）"},
            {"name": "skills", "description": "本班技能（教师可写）"},
            {"name": "conversations", "description": "流式会话（SSE）"},
            {"name": "mcp", "description": "MCP 工具服务器管理与调用审计（仅教师）"},
            {"name": "qa", "description": "班级答疑广场：问题、回复、AI 辅助、FAQ 与统计"},
            {"name": "docs", "description": "接口文档"},
        ],
        "paths": {},
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "token",
                    "description": BEARER_DESC,
                }
            },
            "schemas": {
                "ErrorBody": {
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                            },
                        }
                    },
                },
                "LoginRequest": _json_schema(
                    {
                        "username": {"type": "string", "example": "student_a1"},
                        "password": {"type": "string", "example": "StudentA1#2026"},
                    },
                    ["username", "password"],
                ),
                "LoginResponse": {
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                        "expires_in": {"type": "integer", "example": 28800},
                        "user": {"$ref": "#/components/schemas/UserInfo"},
                    },
                },
                "UserInfo": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "username": {"type": "string"},
                        "role": {"type": "string", "enum": ["teacher", "student"]},
                        "class_id": {"type": "integer"},
                        "class_name": {"type": "string"},
                    },
                },
                "PromptBody": _json_schema(
                    {"body": {"type": "string", "maxLength": 2000}}, ["body"]
                ),
                "SkillSource": _json_schema(
                    {
                        "source": {
                            "type": "string",
                            "maxLength": 8000,
                            "description": (
                                "技能文件原文：空行以上为「键：值」头部（名称/适用条件/工具/"
                                "资料/启用），空行以下为技能说明。"
                            ),
                            "example": (
                                "名称：方程解题引导\n适用条件：方程,移项\n"
                                "工具：knowledge_search\n资料：数学\n启用：是\n\n"
                                "先让学生说出等号两边要保持相等。"
                            ),
                        }
                    },
                    ["source"],
                ),
                "Skill": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string", "maxLength": 32},
                        "trigger": {"type": "string", "maxLength": 120},
                        "subject": {"type": "string"},
                        "tools": {"type": "array", "items": {"type": "string"}},
                        "enabled": {"type": "boolean"},
                        "description": {"type": "string", "maxLength": 2000},
                        "source": {"type": "string"},
                        "created_at": {"type": "string"},
                        "updated_at": {"type": "string"},
                    },
                },
                "Conversation": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "user_id": {"type": "integer"},
                        "class_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "created_at": {"type": "string"},
                        "updated_at": {"type": "string"},
                    },
                },
                "ConversationRequest": _json_schema(
                    {"title": {"type": "string", "maxLength": 100, "example": "新的提问"}}
                ),
                "MessageRequest": _json_schema(
                    {
                        "content": {"type": "string", "minLength": 2, "maxLength": 500},
                        "mode": {
                            "type": "string",
                            "enum": ["guide", "direct"],
                            "default": "guide",
                            "description": (
                                "回答方式：guide 只给思路与第一步（默认）；"
                                "direct 正面回答，给出结论、数量或完整结果。"
                            ),
                        },
                    },
                    ["content"],
                ),
                "Message": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "role": {"type": "string", "enum": ["user", "assistant"]},
                        "content": {"type": "string"},
                        "citations": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Citation"},
                        },
                        "skill_name": {"type": "string"},
                        "status": {"type": "string"},
                        "created_at": {"type": "string"},
                    },
                },
                "Citation": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "integer"},
                        "material_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "chunk_index": {"type": "integer"},
                        "start_offset": {"type": "integer"},
                        "end_offset": {"type": "integer"},
                        "excerpt": {"type": "string"},
                        "material_url": {"type": "string"},
                    },
                },
                "SearchRequest": _json_schema(
                    {
                        "query": {"type": "string", "maxLength": 500},
                        "mode": {
                            "type": "string",
                            "enum": ["keyword", "vector", "hybrid"],
                            "default": "hybrid",
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                    },
                    ["query"],
                ),
                "AskRequest": _json_schema(
                    {"question": {"type": "string", "maxLength": 500}}, ["question"]
                ),
                "McpServer": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string", "maxLength": 64},
                        "base_url": {"type": "string", "maxLength": 512},
                        "has_auth": {
                            "type": "boolean",
                            "description": "是否配置了令牌；响应只回此布尔值，绝不回传令牌原文。",
                        },
                        "connected": {"type": "boolean"},
                        "tool_count": {"type": "integer"},
                        "connected_at": {"type": "string", "nullable": True},
                        "created_at": {"type": "string"},
                    },
                },
                "McpTool": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "schema": {
                            "type": "object",
                            "description": "连接时发现的工具 inputSchema 原样字典。",
                        },
                    },
                },
                "McpToolCall": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "tool_ref": {"type": "string", "description": "工具名@服务器名"},
                        "tool_name": {"type": "string"},
                        "server_name": {"type": "string"},
                        "status": {"type": "string", "enum": ["ok", "denied", "error"]},
                        "detail": {"type": "string"},
                        "username": {"type": "string"},
                        "conversation_id": {"type": "integer", "nullable": True},
                        "created_at": {"type": "string"},
                    },
                },
                "McpServerRequest": _json_schema(
                    {
                        "name": {
                            "type": "string",
                            "maxLength": 64,
                            "description": "小写字母开头，仅含小写字母/数字/连字符，1～64 字符。",
                        },
                        "base_url": {
                            "type": "string",
                            "maxLength": 512,
                            "description": "http/https 开头；填到端口为止，不要带 /mcp。",
                        },
                        "auth_token": {
                            "type": "string",
                            "maxLength": 512,
                            "description": "Bearer 令牌，可空；仅存服务端，响应不回传。",
                        },
                    },
                    ["name", "base_url"],
                ),
                "McpServerUpdate": _json_schema(
                    {
                        "name": {"type": "string", "maxLength": 64},
                        "base_url": {"type": "string", "maxLength": 512},
                        "auth_token": {
                            "type": "string",
                            "maxLength": 512,
                            "description": "空串或缺省表示不修改原令牌。",
                        },
                    },
                ),
            },
        },
    }

    paths = doc["paths"]

    # ---------------------------------------------------------------- auth
    paths["/api/login"] = {
        "post": {
            "tags": ["auth"],
            "summary": "登录并签发 Bearer 令牌",
            "description": "账号密码登录。成功返回 token；错误凭据统一 401，不区分账号是否存在。",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/LoginRequest"}
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "登录成功",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/LoginResponse"}
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
            },
        }
    }
    paths["/api/logout"] = {
        "post": {
            "tags": ["auth"],
            "summary": "登出并吊销当前令牌",
            "security": _bearer_security(),
            "responses": {"200": {"description": "已登出"}, "401": _ERROR_BODY},
        }
    }
    paths["/api/me"] = {
        "get": {
            "tags": ["auth"],
            "summary": "读取当前登录用户",
            "security": _bearer_security(),
            "responses": {
                "200": {
                    "description": "当前身份",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/UserInfo"}
                        }
                    },
                },
                "401": _ERROR_BODY,
            },
        }
    }

    # ------------------------------------------------------------ materials
    paths["/api/materials"] = {
        "get": {
            "tags": ["materials"],
            "summary": "列出本班材料",
            "security": _bearer_security(),
            "responses": {
                "200": {
                    "description": "本班 active 材料（跨班与不存在同样不可见）",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "items": {"type": "array", "items": {"type": "object"}}
                                },
                            }
                        }
                    },
                },
                "401": _ERROR_BODY,
            },
        },
    }
    paths["/api/materials/upload"] = {
        "post": {
            "tags": ["materials"],
            "summary": "教师上传本班材料（.txt/.md，≤10MiB）",
            "security": _bearer_security(),
            "requestBody": {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "file": {"type": "string", "format": "binary"},
                                "title": {"type": "string", "maxLength": 200},
                            },
                            "required": ["file"],
                        }
                    }
                },
            },
            "responses": {
                "201": {"description": "已入库（索引由后台 worker 完成）"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
            },
        }
    }
    paths["/api/materials/{id}"] = {
        "parameters": [_id_path("id", "材料编号")],
        "get": {
            "tags": ["materials"],
            "summary": "读取本班材料详情",
            "security": _bearer_security(),
            "responses": {"200": {"description": "材料详情"}, "401": _ERROR_BODY, "404": _ERROR_BODY},
        },
        "patch": {
            "tags": ["materials"],
            "summary": "教师修改本班材料标题",
            "security": _bearer_security(),
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": _json_schema({"title": {"type": "string", "maxLength": 200}}, ["title"])
                    }
                },
            },
            "responses": {"200": {"description": "已修改"}, "400": _ERROR_BODY, "401": _ERROR_BODY, "403": _ERROR_BODY, "404": _ERROR_BODY},
        },
        "delete": {
            "tags": ["materials"],
            "summary": "教师删除本班材料",
            "security": _bearer_security(),
            "responses": {"204": {"description": "已删除"}, "401": _ERROR_BODY, "403": _ERROR_BODY, "404": _ERROR_BODY},
        },
    }
    paths["/api/materials/{id}/file"] = {
        "parameters": [_id_path("id", "材料编号")],
        "get": {
            "tags": ["materials"],
            "summary": "下载本班材料原文",
            "security": _bearer_security(),
            "responses": {
                "200": {"description": "原文件字节流"},
                "401": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
    }
    paths["/api/materials/{id}/index-status"] = {
        "parameters": [_id_path("id", "材料编号")],
        "get": {
            "tags": ["materials"],
            "summary": "查看索引状态",
            "security": _bearer_security(),
            "responses": {"200": {"description": "状态"}, "401": _ERROR_BODY, "404": _ERROR_BODY},
        },
    }
    paths["/api/materials/{id}/reindex"] = {
        "parameters": [_id_path("id", "材料编号")],
        "post": {
            "tags": ["materials"],
            "summary": "教师重建切片与向量",
            "security": _bearer_security(),
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": _json_schema(
                            {
                                "strategy": {"type": "string", "enum": ["auto", "hierarchy", "custom"]},
                                "chunk_size": {"type": "integer", "minimum": 100, "maximum": 2000},
                                "overlap_ratio": {"type": "number", "minimum": 0, "maximum": 0.5},
                                "separator": {"type": "string"},
                            },
                            ["strategy"],
                        ),
                        "example": {"strategy": "auto"},
                    }
                },
            },
            "responses": {"202": {"description": "已入队"}, "400": _ERROR_BODY, "401": _ERROR_BODY, "403": _ERROR_BODY, "404": _ERROR_BODY},
        },
    }

    # --------------------------------------------------------------- search
    paths["/api/search"] = {
        "post": {
            "tags": ["search"],
            "summary": "检索本班切片",
            "security": _bearer_security(),
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/SearchRequest"}
                    }
                },
            },
            "responses": {
                "200": {"description": "命中列表（无命中为空数组）"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "503": _ERROR_BODY,
            },
        }
    }
    paths["/api/ask"] = {
        "post": {
            "tags": ["search"],
            "summary": "按本班资料作简短回答（非流式）",
            "security": _bearer_security(),
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/AskRequest"}
                    }
                },
            },
            "responses": {
                "200": {"description": "带 [n] 出处标注的回答"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "503": _ERROR_BODY,
            },
        }
    }

    # --------------------------------------------------------------- prompt
    paths["/api/prompt"] = {
        "get": {
            "tags": ["prompt"],
            "summary": "读取本班提示词",
            "security": _bearer_security(),
            "responses": {
                "200": {
                    "description": "当前提示词（未设置为空串）",
                    "content": {
                        "application/json": {
                            "schema": _json_schema(
                                {
                                    "body": {"type": "string"},
                                    "updated_at": {"type": "string", "nullable": True},
                                }
                            )
                        }
                    },
                },
                "401": _ERROR_BODY,
            },
        },
        "put": {
            "tags": ["prompt"],
            "summary": "保存本班提示词（仅教师）",
            "security": _bearer_security(),
            "description": "正文去掉空白后须为 1～2000 个字符；重复保存覆盖原值。",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/PromptBody"}
                    }
                },
            },
            "responses": {
                "200": {"description": "已保存"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
            },
        },
    }

    # --------------------------------------------------------------- skills
    paths["/api/skills"] = {
        "get": {
            "tags": ["skills"],
            "summary": "列出本班技能",
            "security": _bearer_security(),
            "responses": {
                "200": {
                    "description": "技能列表",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "skills": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/Skill"},
                                    }
                                },
                            }
                        }
                    },
                },
                "401": _ERROR_BODY,
            },
        },
        "post": {
            "tags": ["skills"],
            "summary": "用技能文件新建技能（仅教师）",
            "security": _bearer_security(),
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/SkillSource"}
                    }
                },
            },
            "responses": {
                "201": {
                    "description": "已创建",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Skill"}
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
            },
        },
    }
    paths["/api/skills/upload"] = {
        "post": {
            "tags": ["skills"],
            "summary": "上传技能文件并新建技能（仅教师）",
            "security": _bearer_security(),
            "description": (
                "multipart/form-data，字段名 file；仅接受 .md / .txt、UTF-8 文本、≤64KB。\n"
                "文件内容与「技能文件」格式相同（键：值头部 + 一个空行 + 说明）。"
                "解析失败 400 `SKILL_FILE_INVALID`；MCP 工具引用不过保存前四道校验 "
                "400 `MCP_TOOL_INVALID`；同班同名 400 `SKILL_NAME_EXISTS`。"
            ),
            "requestBody": {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "file": {"type": "string", "format": "binary"},
                            },
                            "required": ["file"],
                        }
                    }
                },
            },
            "responses": {
                "201": {
                    "description": "已创建",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Skill"}
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
            },
        }
    }
    paths["/api/skills/{id}"] = {
        "parameters": [_id_path("id", "技能编号")],
        "put": {
            "tags": ["skills"],
            "summary": "用技能文件改写技能（仅教师）",
            "security": _bearer_security(),
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/SkillSource"}
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "已改写",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Skill"}
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
        "delete": {
            "tags": ["skills"],
            "summary": "删除本班技能（仅教师）",
            "security": _bearer_security(),
            "responses": {
                "204": {"description": "已删除，无响应体"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
    }

    # -------------------------------------------------------- conversations
    paths["/api/conversations"] = {
        "get": {
            "tags": ["conversations"],
            "summary": "列出我的会话",
            "security": _bearer_security(),
            "responses": {
                "200": {
                    "description": "按更新时间倒序的会话列表",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "conversations": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/Conversation"},
                                    }
                                },
                            }
                        }
                    },
                },
                "401": _ERROR_BODY,
            },
        },
        "post": {
            "tags": ["conversations"],
            "summary": "新建会话",
            "security": _bearer_security(),
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ConversationRequest"}
                    }
                },
            },
            "responses": {
                "201": {
                    "description": "已创建",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Conversation"}
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
            },
        },
    }
    paths["/api/conversations/{id}"] = {
        "parameters": [_id_path("id", "会话编号")],
        "get": {
            "tags": ["conversations"],
            "summary": "读取会话和消息",
            "security": _bearer_security(),
            "responses": {
                "200": {
                    "description": "会话与全部消息",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "conversation": {"$ref": "#/components/schemas/Conversation"},
                                    "messages": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/Message"},
                                    },
                                },
                            }
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
        "delete": {
            "tags": ["conversations"],
            "summary": "删除本人的会话",
            "security": _bearer_security(),
            "description": (
                "删除会话及其全部消息，无法恢复。他人的会话与不存在统一 404。"
                "MCP 调用审计行保留，只把 conversation_id 置空（审计仍可追溯）。"
            ),
            "responses": {
                "204": {"description": "已删除，无响应体"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
    }
    paths["/api/conversations/{id}/messages"] = {
        "parameters": [_id_path("id", "会话编号")],
        "post": {
            "tags": ["conversations"],
            "summary": "在会话中继续提问（SSE 流式回答）",
            "security": _bearer_security(),
            "description": (
                "响应为 text/event-stream，事件依次为：\n"
                "- `meta`：{\"status\":\"ok|no_hits\",\"citations\":[...],\"skill_name\":\"...\",\"prompt_saved\":bool,\"answer_mode\":\"guide|direct\",\"retrieval_mode\":\"hybrid|keyword\",\"tool_calls\":[{\"ref\",\"status\",\"text\"}]}\n"
                "- `delta`：{\"text\":\"正文分段\"}（若干条）\n"
                "- `done`：{\"message_id\":整数}\n"
                "流开始后若失败，再写一条 `event: error`，HTTP 状态仍为已发出的 200。\n"
                "回答前先检索本班知识库：有嵌入配置时走混合检索（关键词+向量），否则关键词；"
                "命中标注出处，未命中明说资料中未找到。\n"
                "命中带 MCP 工具的技能时，`meta` 在首个 delta 之前带出 `tool_calls`（仅当本次确有调用才出现该键）；"
                "调用点排在推 meta 之前，assistant 消息落库带同一结构，重开会话可见。\n"
                "请求体 `mode=guide`（默认）只给思路；`mode=direct` 正面回答（给出结论、数量或完整结果）。"
            ),
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/MessageRequest"},
                        "example": {"content": "移项怎么做"},
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "SSE 事件流",
                    "content": {
                        "text/event-stream": {
                            "schema": {"type": "string"},
                            "example": (
                                'event: meta\ndata: {"status":"ok","citations":'
                                '[{"number":1,"title":"A 班示例讲义","chunk_index":1}],'
                                '"skill_name":"方程解题引导","prompt_saved":true}\n\n'
                                'event: delta\ndata: {"text":"我先查了你班的资料。"}\n\n'
                                'event: done\ndata: {"message_id":1}\n\n'
                            ),
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "404": _ERROR_BODY,
                "503": _ERROR_BODY,
            },
        },
    }

    # ------------------------------------------------------------------- mcp
    paths["/api/mcp/servers"] = {
        "get": {
            "tags": ["mcp"],
            "summary": "列出本班 MCP 服务器（仅教师）",
            "security": _bearer_security(),
            "description": "每项含工具数量与连接状态；响应只回 has_auth，从不回传令牌原文。跨班数据在服务端即不可见。",
            "responses": {
                "200": {
                    "description": "服务器列表",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "servers": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/McpServer"},
                                    }
                                },
                            }
                        }
                    },
                },
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
            },
        },
        "post": {
            "tags": ["mcp"],
            "summary": "登记本班 MCP 服务器（仅教师）",
            "security": _bearer_security(),
            "description": "登记后为未连接；同班同名返回 400 MCP_NAME_EXISTS；令牌写入服务端，响应只回 has_auth。",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/McpServerRequest"}
                    }
                },
            },
            "responses": {
                "201": {
                    "description": "已登记",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "server": {"$ref": "#/components/schemas/McpServer"}
                                },
                            }
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
            },
        },
    }
    paths["/api/mcp/servers/{id}"] = {
        "parameters": [_id_path("id", "MCP 服务器编号")],
        "put": {
            "tags": ["mcp"],
            "summary": "修改本班 MCP 服务器（仅教师）",
            "security": _bearer_security(),
            "description": (
                "name/base_url 至少给一项（否则 400）；auth_token 空串或缺省表示不修改原令牌；"
                "任何成功 PUT 都把连接置为未连接并清空该服务器工具缓存（需重新连接）。"
            ),
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/McpServerUpdate"}
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "已修改",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "server": {"$ref": "#/components/schemas/McpServer"}
                                },
                            }
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
        "delete": {
            "tags": ["mcp"],
            "summary": "删除本班 MCP 服务器（仅教师）",
            "security": _bearer_security(),
            "description": "工具缓存级联清空；已有调用审计的服务器删除被外键拦下并返回 503 MCP_SERVER_BUSY（先保证据）。",
            "responses": {
                "204": {"description": "已删除，无响应体"},
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
                "503": _ERROR_BODY,
            },
        },
    }
    paths["/api/mcp/servers/{id}/connect"] = {
        "parameters": [_id_path("id", "MCP 服务器编号")],
        "post": {
            "tags": ["mcp"],
            "summary": "连接并发现工具（仅教师）",
            "security": _bearer_security(),
            "description": (
                "对 base_url/mcp 依次 initialize 握手与 tools/list，成功后覆盖写工具缓存并标记已连接；"
                "任一步失败（错令牌、不可达、超时）置回未连接、不动旧缓存，返回 502 可读提示。"
            ),
            "responses": {
                "200": {
                    "description": "连接成功，含本次发现的工具清单",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "server": {"$ref": "#/components/schemas/McpServer"},
                                    "tools": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "description": {"type": "string"},
                                            },
                                        },
                                    },
                                },
                            }
                        }
                    },
                },
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
                "502": _ERROR_BODY,
                "503": _ERROR_BODY,
            },
        },
    }
    paths["/api/mcp/servers/{id}/disconnect"] = {
        "parameters": [_id_path("id", "MCP 服务器编号")],
        "post": {
            "tags": ["mcp"],
            "summary": "断开服务器（仅教师）",
            "security": _bearer_security(),
            "description": "标记未连接并清空该服务器工具缓存；之后绑定其工具的技能调用明确记 denied，不静默成功。",
            "responses": {
                "200": {
                    "description": "已断开",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "server": {"$ref": "#/components/schemas/McpServer"}
                                },
                            }
                        }
                    },
                },
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
    }
    paths["/api/mcp/servers/{id}/tools"] = {
        "parameters": [_id_path("id", "MCP 服务器编号")],
        "get": {
            "tags": ["mcp"],
            "summary": "查看该服务器已发现的工具清单（仅教师）",
            "security": _bearer_security(),
            "responses": {
                "200": {
                    "description": "工具清单",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "tools": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/McpTool"},
                                    }
                                },
                            }
                        }
                    },
                },
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
    }
    paths["/api/mcp/tool-calls"] = {
        "get": {
            "tags": ["mcp"],
            "summary": "查看本班最近调用审计（仅教师，只读）",
            "security": _bearer_security(),
            "description": "按时间倒序；limit 缺省 50、上限 100；班级取自登录会话，不从请求读。",
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": "返回条数，缺省 50，超过 100 按 100 返回。",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                }
            ],
            "responses": {
                "200": {
                    "description": "调用审计（本班、倒序）",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "calls": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/McpToolCall"},
                                    }
                                },
                            }
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
            },
        },
    }

    # ------------------------------------------------------------------ qa
    # 班级答疑广场（小组项目扩展）。跨班与不存在一律 404，与既有材料/会话接口一致。
    qa_question_body = _json_schema(
        {
            "title": {"type": "string", "maxLength": 120, "example": "推导式里的变量作用域"},
            "body": {"type": "string", "maxLength": 5000, "example": "为什么推导式内的变量不泄漏到外层？"},
        },
        ["title", "body"],
    )
    qa_reply_body = _json_schema(
        {"body": {"type": "string", "maxLength": 2000}}, ["body"]
    )
    qa_accept_body = _json_schema({"reply_id": {"type": "integer"}}, ["reply_id"])
    qa_faq_body = _json_schema(
        {
            "question_id": {"type": "integer"},
            "question_text": {"type": "string", "maxLength": 2000},
            "answer_text": {"type": "string", "maxLength": 5000},
        },
        ["question_id", "question_text", "answer_text"],
    )
    qa_faq_edit_body = _json_schema(
        {
            "question_text": {"type": "string", "maxLength": 2000},
            "answer_text": {"type": "string", "maxLength": 5000},
        },
        ["question_text", "answer_text"],
    )
    qa_question_schema = {
        "type": "object",
        "description": "问题对象；status 为 OPEN/ANSWERED/ACCEPTED/CLOSED",
        "properties": {
            "id": {"type": "integer"},
            "class_id": {"type": "integer"},
            "author_id": {"type": "integer"},
            "author_name": {"type": "string"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "status": {"type": "string", "enum": list(("OPEN", "ANSWERED", "ACCEPTED", "CLOSED"))},
            "accepted_reply_id": {"type": "integer", "nullable": True},
            "resolved": {"type": "boolean"},
            "handoff": {"type": "boolean"},
            "handoff_at": {"type": "string", "nullable": True},
            "closed_at": {"type": "string", "nullable": True},
            "reply_count": {"type": "integer"},
            "created_at": {"type": "string"},
        },
    }
    qa_question_id = _id_path("question_id", "问题编号")

    paths["/api/qa/questions"] = {
        "get": {
            "tags": ["qa"],
            "summary": "本班问题列表",
            "security": _bearer_security(),
            "description": (
                "status 可传逗号分隔的状态做筛选；sort 取 new/old/active（active 按回复数倒序）；"
                "page 从 1 开始，size 默认 10、超过 50 按 50 处理；"
                "handoff=1 只看已转人工，unresolved=1 只看 OPEN/ANSWERED。"
                "回复数量只统计人工回复，AI 回答不计入。"
            ),
            "parameters": [
                {"name": "status", "in": "query", "schema": {"type": "string"}},
                {"name": "sort", "in": "query", "schema": {"type": "string", "enum": ["new", "old", "active"]}},
                {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1, "default": 1}},
                {"name": "size", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}},
                {"name": "handoff", "in": "query", "schema": {"type": "string", "enum": ["1"]}},
                {"name": "unresolved", "in": "query", "schema": {"type": "string", "enum": ["1"]}},
            ],
            "responses": {
                "200": {
                    "description": "分页结果",
                    "content": {
                        "application/json": {
                            "schema": _json_schema(
                                {
                                    "items": {"type": "array", "items": qa_question_schema},
                                    "total": {"type": "integer"},
                                    "page": {"type": "integer"},
                                    "size": {"type": "integer"},
                                }
                            )
                        }
                    },
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
            },
        },
        "post": {
            "tags": ["qa"],
            "summary": "发布问题",
            "security": _bearer_security(),
            "description": "标题 1～120 字符、正文 1～5000 字符；新问题状态为 OPEN。",
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": qa_question_body}},
            },
            "responses": {
                "201": {
                    "description": "已创建",
                    "content": {"application/json": {"schema": qa_question_schema}},
                },
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
            },
        },
    }

    paths["/api/qa/questions/{question_id}"] = {
        "get": {
            "tags": ["qa"],
            "summary": "问题详情（含人工回复、最新 AI 回答、FAQ 状态）",
            "security": _bearer_security(),
            "parameters": [qa_question_id],
            "responses": {
                "200": {
                    "description": "详情",
                    "content": {
                        "application/json": {
                            "schema": _json_schema(
                                {
                                    "question": qa_question_schema,
                                    "replies": {"type": "array", "items": {"type": "object"}},
                                    "ai_answer": {"type": "object", "nullable": True},
                                    "ai_answer_count": {"type": "integer"},
                                    "faq": {"type": "object", "nullable": True},
                                }
                            )
                        }
                    },
                },
                "401": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        }
    }

    paths["/api/qa/questions/{question_id}/replies"] = {
        "post": {
            "tags": ["qa"],
            "summary": "回复问题",
            "security": _bearer_security(),
            "description": "回复后状态由 OPEN 推进为 ANSWERED；已关闭问题返回 409。",
            "parameters": [qa_question_id],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": qa_reply_body}},
            },
            "responses": {
                "201": {"description": "已回复"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "404": _ERROR_BODY,
                "409": _ERROR_BODY,
            },
        }
    }

    paths["/api/qa/questions/{question_id}/handoff"] = {
        "post": {
            "tags": ["qa"],
            "summary": "转人工答疑（幂等）",
            "security": _bearer_security(),
            "description": "写入 handoff_at 与 handoff_by，状态不变；重复调用不覆盖首次时间。",
            "parameters": [qa_question_id],
            "responses": {
                "200": {"description": "已标记"},
                "401": _ERROR_BODY,
                "404": _ERROR_BODY,
                "409": _ERROR_BODY,
            },
        }
    }

    paths["/api/qa/questions/{question_id}/ai-answer"] = {
        "post": {
            "tags": ["qa"],
            "summary": "AI 辅助解答（SSE）",
            "security": _bearer_security(),
            "description": (
                "复用本班检索与流式生成：事件依次为 meta、若干 delta、done，流中失败补 error。"
                "meta 含 status（ok/no_hits）、citations、retrieval_mode、ai_generated=true。"
                "回答落 qa_ai_answers，不推进问题状态、不计入回复数。"
                "检索服务不可用时返回 503；已关闭问题返回 409。"
            ),
            "parameters": [qa_question_id],
            "responses": {
                "200": {
                    "description": "text/event-stream",
                    "content": {"text/event-stream": {"schema": {"type": "string"}}},
                },
                "401": _ERROR_BODY,
                "404": _ERROR_BODY,
                "409": _ERROR_BODY,
                "503": _ERROR_BODY,
            },
        }
    }

    paths["/api/qa/questions/{question_id}/accept"] = {
        "post": {
            "tags": ["qa"],
            "summary": "采纳回答（仅教师）",
            "security": _bearer_security(),
            "description": (
                "回复必须属于当前问题，否则 400 QA_REPLY_NOT_IN_QUESTION。"
                "成功后状态变 ACCEPTED、记录 accepted_reply_id 与 resolved_at；"
                "对已关闭问题采纳不会把状态改回 ACCEPTED，但会保留解决记录。"
            ),
            "parameters": [qa_question_id],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": qa_accept_body}},
            },
            "responses": {
                "200": {"description": "已采纳"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
        "delete": {
            "tags": ["qa"],
            "summary": "取消采纳（仅教师）",
            "security": _bearer_security(),
            "description": "清空采纳标记，状态回到 ANSWERED（有回复）或 OPEN；未采纳时 400。",
            "parameters": [qa_question_id],
            "responses": {
                "200": {"description": "已取消"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
    }

    paths["/api/qa/questions/{question_id}/close"] = {
        "post": {
            "tags": ["qa"],
            "summary": "关闭问题（仅教师）",
            "security": _bearer_security(),
            "description": "关闭后不可再回复或转人工；accepted_reply_id 保留，已解决统计不受影响。",
            "parameters": [qa_question_id],
            "responses": {
                "200": {"description": "已关闭"},
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
                "409": _ERROR_BODY,
            },
        }
    }

    paths["/api/qa/questions/{question_id}/reopen"] = {
        "post": {
            "tags": ["qa"],
            "summary": "重新打开（仅教师）",
            "security": _bearer_security(),
            "description": "回到 ACCEPTED（曾采纳）、ANSWERED（有回复）或 OPEN；未关闭时 409。",
            "parameters": [qa_question_id],
            "responses": {
                "200": {"description": "已打开"},
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
                "409": _ERROR_BODY,
            },
        }
    }

    paths["/api/qa/questions/{question_id}/faq-draft"] = {
        "get": {
            "tags": ["qa"],
            "summary": "生成 FAQ 草稿（仅教师，不落库）",
            "security": _bearer_security(),
            "description": "仅已采纳有效回答的问题可生成；未采纳返回 400 QA_NOT_RESOLVED。",
            "parameters": [qa_question_id],
            "responses": {
                "200": {"description": "草稿"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        }
    }

    paths["/api/qa/faqs"] = {
        "get": {
            "tags": ["qa"],
            "summary": "本班 FAQ 列表",
            "security": _bearer_security(),
            "description": "学生只能看到已发布条目；教师加 include_revoked=1 可含已撤销。",
            "parameters": [
                {"name": "include_revoked", "in": "query", "schema": {"type": "string", "enum": ["1"]}}
            ],
            "responses": {
                "200": {
                    "description": "列表",
                    "content": {
                        "application/json": {
                            "schema": _json_schema({"items": {"type": "array", "items": {"type": "object"}}})
                        }
                    },
                },
                "401": _ERROR_BODY,
            },
        },
        "post": {
            "tags": ["qa"],
            "summary": "发布 FAQ（仅教师）",
            "security": _bearer_security(),
            "description": (
                "只有已采纳的问题可发布；同一问题唯一，重复发布返回 409 QA_FAQ_EXISTS。"
                "发布后把本班已发布 FAQ 汇总成一份材料并触发索引重建。"
            ),
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": qa_faq_body}},
            },
            "responses": {
                "201": {"description": "已发布"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
                "409": _ERROR_BODY,
            },
        },
    }

    paths["/api/qa/faqs/{faq_id}"] = {
        "get": {
            "tags": ["qa"],
            "summary": "FAQ 详情",
            "security": _bearer_security(),
            "description": "学生请求已撤销 FAQ 返回 404。",
            "parameters": [_id_path("faq_id", "FAQ 编号")],
            "responses": {"200": {"description": "详情"}, "401": _ERROR_BODY, "404": _ERROR_BODY},
        },
        "put": {
            "tags": ["qa"],
            "summary": "编辑 FAQ（仅教师）",
            "security": _bearer_security(),
            "description": "教师编辑后保存的是新快照，同时重建汇总材料。",
            "parameters": [_id_path("faq_id", "FAQ 编号")],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": qa_faq_edit_body}},
            },
            "responses": {
                "200": {"description": "已保存"},
                "400": _ERROR_BODY,
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
            },
        },
        "delete": {
            "tags": ["qa"],
            "summary": "撤销 FAQ（仅教师，软删）",
            "security": _bearer_security(),
            "description": "status 改为 revoked，行保留；汇总材料正文移除该条。已撤销再次撤销返回 409。",
            "parameters": [_id_path("faq_id", "FAQ 编号")],
            "responses": {
                "204": {"description": "已撤销"},
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
                "409": _ERROR_BODY,
            },
        },
    }

    paths["/api/qa/faqs/{faq_id}/republish"] = {
        "post": {
            "tags": ["qa"],
            "summary": "重新发布 FAQ（仅教师）",
            "security": _bearer_security(),
            "description": "仅对已撤销的 FAQ 有效；已发布时返回 409 QA_FAQ_PUBLISHED。",
            "parameters": [_id_path("faq_id", "FAQ 编号")],
            "responses": {
                "200": {"description": "已重新发布"},
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
                "404": _ERROR_BODY,
                "409": _ERROR_BODY,
            },
        }
    }

    paths["/api/qa/stats"] = {
        "get": {
            "tags": ["qa"],
            "summary": "本班答疑统计（仅教师）",
            "security": _bearer_security(),
            "description": (
                "pending（OPEN/ANSWERED）、resolved（accepted_reply_id 非空，含已关闭）、"
                "closed_unresolved（已关闭且未采纳）三项之和恒等于 total；"
                "top_questions 按人工回复数排序，不计 AI 回答。"
            ),
            "responses": {
                "200": {
                    "description": "统计结果",
                    "content": {
                        "application/json": {
                            "schema": _json_schema(
                                {
                                    "pending": {"type": "integer"},
                                    "resolved": {"type": "integer"},
                                    "closed_unresolved": {"type": "integer"},
                                    "handoff_pending": {"type": "integer"},
                                    "total": {"type": "integer"},
                                    "faq_total": {"type": "integer"},
                                    "top_questions": {"type": "array", "items": {"type": "object"}},
                                    "trend": {"type": "array", "items": {"type": "object"}},
                                }
                            )
                        }
                    },
                },
                "401": _ERROR_BODY,
                "403": _ERROR_BODY,
            },
        }
    }

    # ----------------------------------------------------------------- docs
    paths["/health"] = {
        "get": {
            "tags": ["auth"],
            "summary": "存活检查（无需登录）",
            "responses": {"200": {"description": "{\"status\":\"ok\"}"}},
        }
    }
    paths["/openapi.json"] = {
        "get": {
            "tags": ["docs"],
            "summary": "读取 OpenAPI 文档（无需登录）",
            "responses": {"200": {"description": "OpenAPI 3 JSON"}},
        }
    }
    paths["/swagger/index.html"] = {
        "get": {
            "tags": ["docs"],
            "summary": "打开 Swagger UI（无需登录）",
            "responses": {"200": {"description": "Swagger UI 页面"}},
        }
    }
    return doc


def openapi_document() -> dict:
    """返回文档副本，避免调用方改动共享结构。"""
    return copy.deepcopy(build_openapi())
