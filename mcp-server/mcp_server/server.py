"""FastMCP 实例、两个示范工具、Bearer 门禁与 ``/health`` 探针。

* ``mcp``：FastMCP 实例（``streamable_http`` + 无状态 + JSON 响应），工具用
  ``@mcp.tool()`` 声明，docstring 即 tools/list 里的 description。
* 两个工具：``formula_hint``（只给步骤提示，绝不给最终数值答案）与
  ``unit_convert``（仅米↔厘米、千克↔克；不支持的单位返回可读文本而非报错）。
* ``BearerGate``：裸 ASGI 中间件，只拦 ``/mcp`` 前缀校验 Bearer；``/health``
  在门禁里直接应答不鉴权；其余（含 lifespan）原样转发给 FastMCP 应用。
* ``create_app()``：工厂，返回包好门禁的 ASGI 应用，供 uvicorn 与 apitest 复用。

实现要点（坑与解法，均在 langdev 环境实测通过）：

1. 不用 Starlette ``Mount`` 挂 ``/health``——``Mount`` 不向子应用转发
   lifespan，FastMCP 的 streamable manager 会 500（Task group is not
   initialized）。``/health`` 改在门禁里直接回，lifespan 透传给 FastMCP。
2. **不设 ``json_response=True``**（用默认的 SSE 响应）。实测：开了
   ``json_response=True`` 后，官方客户端 ``tools/call`` 必失败——mcp 1.30 的
   ``call_tool`` 在校验 structuredContent 时会额外发一次 ``tools/list``，而
   JSON 响应模式下同一会话第 3 个请求就报 ``Session terminated``。默认 SSE
   响应下 discover/call 均正常。代价是裸 HTTP（curl）拿到的是 SSE 报文而非
   纯 JSON，解析时取 ``data:`` 行即可；``/health`` 与 401 仍由门禁直接回 JSON。
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

#: 服务名：tools/list 与 /health 对外标识，亦为技能引用里的「服务器名」示例。
SERVICE_NAME = "campus-tools"

#: 长度换算到「米」的系数（仅支持米与厘米）。
_LENGTH_TO_METER: dict[str, float] = {"m": 1.0, "cm": 0.01}

#: 质量换算到「千克」的系数（仅支持千克与克）。
_MASS_TO_KILOGRAM: dict[str, float] = {"kg": 1.0, "g": 0.001}


mcp = FastMCP(
    SERVICE_NAME,
    streamable_http_path="/mcp",
    stateless_http=True,
)


@mcp.tool()
def formula_hint(query: str) -> str:
    """根据学生问题给出公式或步骤提示，不给出最终数值答案。"""
    text = query.strip()
    lowered = text.lower()
    # 按关键词给分类步骤提示；绝不计算或给出最终答案，只指方向与第一步。
    if any(word in text for word in ("去括号", "括号", "展开", "分配律")):
        return (
            "这类题先用分配律去括号：把括号外的系数分别乘进括号内每一项，"
            "注意符号变化。去括号后再合并同类项。"
            "请你自己写出每一步，我可以帮你检查。"
        )
    if any(word in text for word in ("移项", "方程", "等式", "解方程", "一元一次", "未知数")):
        return (
            "解方程的关键是等式两边保持相等：把含未知数的项移到一边、常数项移到另一边，"
            "移项要变号。两边再同时除以未知数的系数。"
            "先把方程原样写出来，我们一起看第一步怎么移。"
        )
    if any(word in text for word in ("面积", "体积", "周长")):
        return (
            "先判断图形类别，再选择对应公式：长方形面积=长×宽，正方形面积=边长×边长，"
            "三角形面积=底×高÷2，圆面积=π×半径²。"
            "告诉我你求的是哪个图形，我帮你对公式。"
        )
    if any(word in text for word in ("分数", "通分", "约分", "分母")):
        return (
            "分数加减先看分母：同分母直接加减分子，异分母先通分成同分母再算；"
            "结果能约分的要约成最简。乘法分子乘分子、分母乘分母，除法转化为乘以倒数。"
        )
    if not text:
        return "请把具体题目或问题描述发给我，我再给出对应的公式或第一步思路。"
    return (
        "先审题：把已知条件和所求结论分别列出来，再回想课本里哪个知识点管这类问题，"
        "把对应的公式或定理写出来，从第一步开始代入。"
        "你可以先把题目复述一遍，我来帮你对第一步。"
    )


@mcp.tool()
def unit_convert(value: float, from_unit: str, to_unit: str) -> str:
    """米与厘米、千克与克之间的简单换算。"""
    source = from_unit.strip().lower()
    target = to_unit.strip().lower()
    # 同一单位：无需换算（含未知单位也如实说明，不报错）。
    if source == target:
        return f"{value:g} {source} 与 {target} 是同一单位，数值不变。"
    if source in _LENGTH_TO_METER and target in _LENGTH_TO_METER:
        result = value * _LENGTH_TO_METER[source] / _LENGTH_TO_METER[target]
        return f"{value:g} {source} = {result:g} {target}"
    if source in _MASS_TO_KILOGRAM and target in _MASS_TO_KILOGRAM:
        result = value * _MASS_TO_KILOGRAM[source] / _MASS_TO_KILOGRAM[target]
        return f"{value:g} {source} = {result:g} {target}"
    # 不支持的单位返回可读文本而非报错。
    return (
        f"暂不支持 {source} 与 {target} 之间的换算；"
        "本工具仅支持米↔厘米、千克↔克。"
    )


class BearerGate:
    """裸 ASGI 门禁：``/health`` 直接应答不鉴权；``/mcp`` 前缀校验 Bearer。

    其余请求（含 lifespan）原样转发给内层 FastMCP 应用，保证 streamable
    session manager 的 lifespan 正常运行（不重犯 Starlette Mount 的坑）。
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == "/health" or path.startswith("/health/"):
                await JSONResponse(
                    {"status": "ok", "service": SERVICE_NAME}
                )(scope, receive, send)
                return
            if path.startswith("/mcp"):
                headers = dict(scope.get("headers") or [])
                auth = headers.get(b"authorization", b"").decode()
                if auth != f"Bearer {self.token}":
                    await JSONResponse(
                        {"error": "缺少或无效的 Bearer 令牌"}, status_code=401
                    )(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def create_app(token: str | None = None) -> BearerGate:
    """工厂：返回包好 Bearer 门禁的 ASGI 应用。

    ``token`` 缺省从环境变量 ``MCP_AUTH_TOKEN`` 读取；apitest 先设好环境变量
    再 import 本函数即可拿到带鉴权的进程内真实服务。
    """
    if token is None:
        token = os.environ.get("MCP_AUTH_TOKEN", "")
    return BearerGate(mcp.streamable_http_app(), token=token)
