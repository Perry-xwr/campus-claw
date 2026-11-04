"""MCP 传输门面：主机侧经 ``langchain-mcp-adapters`` 连接远端工具服务。

只承担「传报文」：``initialize``（自动握手）、``tools/list``、``tools/call``。
「要不要调、调哪个、传什么参」由 :mod:`campusclaw.mcp_skill` 决定，本模块不做编排。

关键纪律（坑与解法，langdev 实测通过）：

* **每次调用都新建事件循环与客户端**：Flask 视图是同步的，用 ``asyncio.run()``
  一次操作一个 loop；client/session 用完即弃，绝不提到模块级或跨请求复用
  （anyio 资源跨 loop 绑定会报错）。
* **失败统一转** :class:`McpCallError`：可读文案，不含堆栈、URL 与令牌。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

#: 连接发现与工具调用的统一超时（秒）。
CONNECT_TIMEOUT = 10

_SERVER_KEY = "server"


class McpCallError(Exception):
    """远端调用失败：可读文案，不含堆栈、令牌与 URL 细节。"""


def _http_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """构造直连的 httpx 客户端：``trust_env=False`` 强制不走 HTTP 代理。

    MCP 服务器都是内网服务（本机回环或容器网络），绝不应经 http_proxy 等环境
    变量中转——否则本地连接会被代理拦截、不可达地址也只会拿到代理的 502 而非
    真实连接错误。其余参数与官方 ``create_mcp_http_client`` 对齐。
    """
    kwargs: dict[str, Any] = {"trust_env": False, "timeout": timeout}
    if headers is not None:
        kwargs["headers"] = headers
    if auth is not None:  # pragma: no cover - 本仓不使用自定义 auth
        kwargs["auth"] = auth
    return httpx.AsyncClient(**kwargs)


def _connection(base_url: str, token: str, timeout: int = CONNECT_TIMEOUT) -> dict:
    """构造 MultiServerMCPClient 的连接字典：streamable_http + Bearer + 超时。"""
    return {
        "transport": "streamable_http",
        "url": base_url.rstrip("/") + "/mcp",
        "headers": {"Authorization": f"Bearer {token}"} if token else {},
        "timeout": timeout,
        "httpx_client_factory": _http_client_factory,
    }


def _text_of(result: Any) -> str:
    """取 tools/call 结果里第一个文本块的文本；没有则返回空串。"""
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text:
            return text
    return ""


def _readable(exc: BaseException) -> str:
    """把任意异常转成一句可读文案，不泄露堆栈、URL 与令牌。

    先深入 ``ExceptionGroup`` 取出根因，再按根因类型映射到固定提示；
    网络类错误绝不回显原始报文（其中常含完整 URL）。
    """
    root: BaseException = exc
    depth = 0
    while getattr(root, "exceptions", None) and depth < 10:
        root = root.exceptions[0]
        depth += 1
    text = str(root)
    lowered = text.lower()
    if any(word in lowered for word in ("timed out", "timeout", "read operation", "readtimeout")):
        return "无法连接 MCP 服务器（连接超时），请检查地址与令牌"
    if "401" in text or "unauthorized" in lowered or "forbidden" in lowered:
        return "无法连接 MCP 服务器（鉴权失败），请检查地址与令牌"
    if any(
        word in lowered
        for word in (
            "refused",
            "unreachable",
            "connect",
            "network",
            "getaddrinfo",
            "resolution",
            "ssl",
            "certificate",
            "reset",
            "broken pipe",
            "bad gateway",
            "gateway",
            "502",
            "503",
            "504",
        )
    ):
        return "无法连接 MCP 服务器（连接失败），请检查地址与令牌"
    return "无法连接 MCP 服务器（协议或响应异常），请检查地址与令牌"


def discover_tools(
    base_url: str, token: str, timeout: int = CONNECT_TIMEOUT
) -> list[dict[str, Any]]:
    """initialize + tools/list；返回 ``[{name, description, schema}]``。

    ``schema`` 为远端 ``inputSchema`` 原样字典。握手或发现任一步失败抛
    :class:`McpCallError`（错令牌、不可达、超时均如此）。
    """

    async def _run() -> list[dict[str, Any]]:
        client = MultiServerMCPClient(
            {_SERVER_KEY: _connection(base_url, token, timeout)}
        )
        async with client.session(_SERVER_KEY) as session:
            result = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "schema": dict(tool.inputSchema or {}),
                }
                for tool in result.tools
            ]

    try:
        return asyncio.run(_run())
    except McpCallError:
        raise
    except Exception as exc:
        raise McpCallError(_readable(exc)) from None


def call_tool(
    base_url: str,
    token: str,
    tool_name: str,
    arguments: dict[str, Any],
    timeout: int = CONNECT_TIMEOUT,
) -> str:
    """tools/call；取第一个 text 块；``isError`` 或异常统一转 :class:`McpCallError`。"""

    async def _run() -> str:
        client = MultiServerMCPClient(
            {_SERVER_KEY: _connection(base_url, token, timeout)}
        )
        async with client.session(_SERVER_KEY) as session:
            result = await session.call_tool(tool_name, arguments)
            if result.isError:
                raise McpCallError(_text_of(result) or "工具执行失败")
            return _text_of(result)

    try:
        return asyncio.run(_run())
    except McpCallError:
        raise
    except Exception as exc:
        raise McpCallError(_readable(exc)) from None
