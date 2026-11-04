"""mcp-server 启动入口：``python -m mcp_server``。

``MCP_AUTH_TOKEN`` 缺失或空白时打印可读提示并非零退出，不进入可用状态；
否则以 uvicorn 运行 :func:`mcp_server.server.create_app` 返回的 ASGI 应用。
"""

from __future__ import annotations

import os
import sys

TOKEN_ENV = "MCP_AUTH_TOKEN"
DEFAULT_PORT = 8090


def _resolve_token() -> str:
    """读取并校验 Bearer 令牌；缺失/空白时退出进程（退出码 2）。"""
    token = os.environ.get(TOKEN_ENV, "")
    if not token.strip():
        sys.stderr.write(
            f"启动失败：缺少环境变量 {TOKEN_ENV}。\n"
            f"请先设置非空白的 Bearer 令牌后再启动，例如：\n"
            f"    {TOKEN_ENV}=<你的令牌> python -m mcp_server\n"
            "令牌只从环境变量读取，不写入代码、镜像或日志。\n"
        )
        raise SystemExit(2)
    return token


def main() -> None:
    token = _resolve_token()
    # 延迟 import：缺令牌时不应触发 uvicorn / FastMCP 的启动副作用。
    import uvicorn

    from mcp_server.server import create_app

    try:
        port = int(os.environ.get("MCP_PORT", str(DEFAULT_PORT)))
    except ValueError:
        port = DEFAULT_PORT
    uvicorn.run(create_app(token), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
