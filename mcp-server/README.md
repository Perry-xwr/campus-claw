# mcp-server：CampusClaw 自建 MCP 工具服务（campus-tools）

第 6 课「MCP 与工具接入」的同仓工具服务。它在 HTTP 上实现 MCP 的
JSON-RPC 2.0 协议（`initialize` / `tools/list` / `tools/call`），用 Bearer
令牌鉴权；主机侧（Flask 主应用）登记本班服务器后即可连接、发现并调用这里的工具。

- 服务名：`campus-tools`
- 协议：`POST /mcp`（JSON-RPC 2.0，Streamable HTTP）
- 健康检查：`GET /health` → `{"status":"ok","service":"campus-tools"}`（免鉴权）
- 鉴权：`/mcp` 前缀校验 `Authorization: Bearer <MCP_AUTH_TOKEN>`

## 工具

| 工具 | 入参 | 说明 |
| --- | --- | --- |
| `formula_hint` | `query: str` | 按关键词给公式或步骤提示（去括号/移项/面积/分数类），**不给最终数值答案**；无命中给通用第一步引导。 |
| `unit_convert` | `value: float, from_unit: str, to_unit: str` | 仅支持米↔厘米、千克↔克；不支持的单位返回可读文本而非报错。入参名用 `from_unit` 规避 Python 关键字 `from`。 |

## 令牌

令牌只从环境变量 `MCP_AUTH_TOKEN` 读取，**不进 Git、不进镜像、不进前端、不进日志**：

- 不设置或空白 → 进程打印可读提示并非零退出，不进入可用状态；
- 无令牌 / 错令牌请求 `/mcp` → 401 JSON，不进入工具执行。

## 本地运行

在 `mcp-server/` 目录下（依赖见项目根 `requirements.txt`，需 `mcp` 与 `uvicorn`）：

```bash
cd mcp-server
MCP_AUTH_TOKEN=<你的令牌> python -m mcp_server
# 默认监听 0.0.0.0:8090；可用 MCP_PORT 覆盖
```

裸 HTTP 调 `/mcp` 必须带 `Accept: application/json, text/event-stream` 头（MCP 规范）。
服务端用默认的 SSE 响应（官方客户端 `tools/call` 在 JSON 响应模式下会失败，见
`server.py` 顶部说明），所以 curl 看到的是 `event: message` + `data: {...}` 报文，
结果取 `data:` 行即可：

```bash
curl -s http://127.0.0.1:8090/health
curl -s -N -X POST http://127.0.0.1:8090/mcp \
  -H "Authorization: Bearer <你的令牌>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## 教师登记用的 Base URL

教师在主应用「MCP」页登记服务器时，**Base URL 填到端口为止，不要带 `/mcp` 后缀**：

- Compose 环境（容器网络内以服务名解析）：`http://mcp:8090`
- 本机直连：`http://127.0.0.1:8090`

登记时填的令牌须与 `MCP_AUTH_TOKEN` 一致；主机侧调用时自动拼 `/mcp` 并带上 Bearer。

## Compose

`docker compose up` 会与主应用一并启动 `mcp` 服务（同镜像、不同 command），
宿主机 `127.0.0.1:8090` 可达；令牌经环境变量 `MCP_AUTH_TOKEN` 注入（项目根 `.env`）。
