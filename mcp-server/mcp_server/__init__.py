"""CampusClaw 第 6 课自建 MCP 工具服务（campus-tools）。

独立 ASGI 服务：在 HTTP 上实现 MCP 的 JSON-RPC 2.0 协议
（``initialize`` / ``tools/list`` / ``tools/call``），Bearer 令牌从环境变量
``MCP_AUTH_TOKEN`` 读取，``GET /health`` 免鉴权。

本地运行（在 ``mcp-server/`` 目录下）::

    MCP_AUTH_TOKEN=<你的令牌> python -m mcp_server

详见同目录 ``README.md``。
"""

from __future__ import annotations

from mcp_server.server import BearerGate, create_app, mcp

__all__ = ["BearerGate", "create_app", "mcp"]
