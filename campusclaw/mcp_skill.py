"""MCP 技能绑定与确定性工具调用编排。

职责（对应 design.md 第 4 章）：

* :func:`validate_tool_refs`：保存技能前对每条 MCP 引用过四道校验
  （格式 → 服务器存在且属本班 → 已连接 → 工具在已发现清单），任一不过整份拒绝。
* :func:`build_tool_arguments`：按工具 ``inputSchema`` 的 ``required`` 取参——
  query 类键填本次提问原文，其余键从代码给定的演示参数补齐，仍缺不填。
* :func:`sanitize_tool_output`：工具返回的信任边界，命中已知载荷或超长整条丢弃。
* :func:`run_skill_tools`：命中技能后、推 ``meta`` 前按白名单逐个调用，
  产出 ``[{ref, status, text}]`` 三态，并写调用审计（两种 denied 的写/不写规则不同）。

引用格式（``MCP_TOOL_REF_RE`` / ``is_mcp_tool_ref`` / ``split_tool_refs``）只在
:mod:`campusclaw.tutor_db` 定义一次，这里复用，不重复声明。
"""

from __future__ import annotations

import logging
from typing import Any

from campusclaw import mcp_client, mcp_db, tutor_db
from campusclaw.errors import ApiError

logger = logging.getLogger(__name__)

#: query 类入参名：required 中这些键填本次提问原文。
_QUERY_KEYS = ("query", "question", "text", "input")

#: 代码给定的演示参数：required 中非 query 类键由此补齐（演示只有一个工具需要）。
DEMO_FIXED_ARGS: dict[str, dict[str, Any]] = {
    "unit_convert": {"value": 5, "from_unit": "m", "to_unit": "cm"},
}

#: 工具输出安全校验：命中任一已知指令式句式即整条丢弃（英文忽略大小写）。
_UNSAFE_MARKERS = (
    "忽略前述请求",
    "ignore previous instructions",
    "你现在是",
    "system:",
)

#: 工具输出长度上限（字），超过即整条丢弃。
_MAX_TOOL_OUTPUT = 1200

#: 未通过安全校验时替换成的固定说明（同时用于 tool_calls.text 与进 prompt 的文本）。
SANITIZED_MESSAGE = "（该工具返回的内容未通过安全校验，已丢弃，不作为回答依据。）"


def validate_tool_refs(
    conn: Any, class_id: int, tools: list[str]
) -> None:
    """保存前四道校验：任一不过抛 ``ApiError(400, "MCP_TOOL_INVALID", 可读原因)``。

    他班服务器名与不存在的名字走同一条查询（按 class_id 过滤），得到完全一致的
    「不存在或不属于本班」文案，不可区分。
    """
    for item in tools:
        if item == "knowledge_search":
            continue
        if not tutor_db.is_mcp_tool_ref(item):
            raise ApiError(
                400,
                "MCP_TOOL_INVALID",
                f"MCP 工具引用「{item}」格式不合法，应写「工具名@服务器名」，"
                "例如 formula_hint@campus-tools",
            )
        tool_name, _, server_name = item.partition("@")
        server = mcp_db.get_server_by_name(conn, class_id, server_name)
        if server is None:
            raise ApiError(
                400,
                "MCP_TOOL_INVALID",
                f"MCP 服务器「{server_name}」不存在或不属于本班",
            )
        if not server["connected"]:
            raise ApiError(
                400,
                "MCP_TOOL_INVALID",
                f"MCP 服务器「{server_name}」尚未连接，请先连接并发现工具",
            )
        tool = mcp_db.get_tool(conn, int(server["id"]), tool_name)
        if tool is None:
            raise ApiError(
                400,
                "MCP_TOOL_INVALID",
                f"工具「{tool_name}」不在服务器「{server_name}」已发现的清单中",
            )


def build_tool_arguments(schema: dict[str, Any] | None, question: str) -> dict[str, Any]:
    """按 ``inputSchema`` 的 ``required`` 组装调用参数。

    * 键属于 ``("query","question","text","input")`` → 填本次提问原文；
    * 其余键从 :data:`DEMO_FIXED_ARGS` 给出的演示值补齐；
    * 仍缺的键不填（远端报错则记 error）。
    """
    required = list((schema or {}).get("required") or [])
    demo_values: dict[str, Any] = {}
    for args in DEMO_FIXED_ARGS.values():
        demo_values.update(args)
    arguments: dict[str, Any] = {}
    for key in required:
        if key in _QUERY_KEYS:
            arguments[key] = question
        elif key in demo_values:
            arguments[key] = demo_values[key]
    return arguments


def sanitize_tool_output(text: str) -> tuple[str, bool]:
    """工具输出信任边界：命中已知载荷或超长 → 整条丢弃，返回 ``(固定说明, False)``。"""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in _UNSAFE_MARKERS):
        return SANITIZED_MESSAGE, False
    if len(text) > _MAX_TOOL_OUTPUT:
        return SANITIZED_MESSAGE, False
    return text, True


def _record(
    conn: Any,
    class_id: int,
    server_id: int,
    tool_ref: str,
    status: str,
    detail: str,
    user_id: int,
    conversation_id: int | None,
) -> None:
    """写一行审计；审计失败只记日志，不阻断工具结果与主流程。"""
    try:
        mcp_db.record_tool_call(
            conn, class_id, server_id, tool_ref, status, detail, user_id, conversation_id
        )
    except Exception:
        logger.exception("记录 MCP 调用审计失败：%s %s", tool_ref, status)


def run_skill_tools(
    conn: Any,
    class_id: int,
    skill: dict[str, Any] | None,
    question: str,
    user_id: int,
    conversation_id: int | None,
) -> list[dict[str, Any]]:
    """按技能工具白名单确定性调用 MCP 工具，返回 ``[{ref, status, text}]``。

    时序（design.md 4.2）：跳过 ``knowledge_search``；按名查服务器——

    * 查不到（被改名/删除）→ ``denied``，**不写审计**（无处可挂）；
    * 存在但未连接 → ``denied`` + 审计（detail=服务器未连接）；
    * 已连接 → 取缓存 schema → 取参 → 调用：
        - 工具不在缓存 → ``error`` + 审计（工具未在已发现的清单中）；
        - 调用失败 → ``error`` + 审计（错误原因）；
        - 调用成功 → 过安全校验 → ``ok`` + 审计（结果前 200 字；未过校验时注明）。

    整体 try/except 兜底：任何异常只记日志并返回已收集结果，绝不向上抛。
    """
    results: list[dict[str, Any]] = []
    try:
        for ref in (skill or {}).get("tools") or []:
            if ref == "knowledge_search":
                continue
            if not tutor_db.is_mcp_tool_ref(ref):
                # 保存前已校验格式；运行期兜底：无法归属服务器，按 denied 不写审计。
                results.append(
                    {"ref": ref, "status": "denied", "text": "工具引用格式不合法，未调用"}
                )
                continue
            tool_name, _, server_name = ref.partition("@")
            server = mcp_db.get_server_by_name(conn, class_id, server_name)
            if server is None:
                # 服务器按名查不到：denied，不写审计。
                results.append(
                    {
                        "ref": ref,
                        "status": "denied",
                        "text": f"服务器 {server_name} 不存在或已被删除，未调用",
                    }
                )
                continue
            server_id = int(server["id"])
            if not server["connected"]:
                _record(
                    conn, class_id, server_id, ref, "denied", "服务器未连接",
                    user_id, conversation_id,
                )
                results.append(
                    {
                        "ref": ref,
                        "status": "denied",
                        "text": f"服务器 {server_name} 未连接，未调用",
                    }
                )
                continue
            tool = mcp_db.get_tool(conn, server_id, tool_name)
            if tool is None:
                detail = "工具未在已发现的清单中"
                _record(
                    conn, class_id, server_id, ref, "error", detail,
                    user_id, conversation_id,
                )
                results.append({"ref": ref, "status": "error", "text": detail})
                continue
            arguments = build_tool_arguments(tool.get("schema"), question)
            try:
                raw = mcp_client.call_tool(
                    server["base_url"], server["auth_token"], tool_name, arguments
                )
            except mcp_client.McpCallError as exc:
                reason = str(exc)
                _record(
                    conn, class_id, server_id, ref, "error", reason,
                    user_id, conversation_id,
                )
                results.append({"ref": ref, "status": "error", "text": reason})
                continue
            except Exception:
                logger.exception("MCP 工具调用异常：%s", ref)
                reason = "工具调用失败"
                _record(
                    conn, class_id, server_id, ref, "error", reason,
                    user_id, conversation_id,
                )
                results.append({"ref": ref, "status": "error", "text": reason})
                continue
            sanitized, passed = sanitize_tool_output(raw)
            if passed:
                detail = sanitized[:200]
            else:
                detail = "结果未通过安全校验，已丢弃，不作为回答依据"
            _record(
                conn, class_id, server_id, ref, "ok", detail,
                user_id, conversation_id,
            )
            results.append({"ref": ref, "status": "ok", "text": sanitized})
    except Exception:
        # 整体兜底：局部失败不阻断检索与流式回答。
        logger.exception("run_skill_tools 编排失败")
    return results
