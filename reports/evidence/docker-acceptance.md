# 容器环境验收记录（判据 2「环境可复现」的实跑证据）

- 采集时间：2026-11-12 21:25–21:36（GMT+8）
- 宿主机：Windows，Docker Desktop 4.99.0，引擎 Linux 模式
- 客户端 / 服务端：`docker 29.9.3` / `29.9.3`，`Docker Compose v5.7.0`
- 引擎资源：16 核 / 7.9 GiB / overlayfs
- 项目：`D:\campus-claw`（提交 `0b7f358` 之后的本轮改动）

本文件只记录**实际执行过**的命令与返回值。未执行的不写进结论。

---

## 一、构建

```
docker compose build --progress plain
```

- 首次构建（改 pip 源前）：**失败**。`RUN pip install` 阶段 369 秒后报
  `[Errno 101] Network is unreachable`，5 次重试全部落空。
- 排查：容器内 DNS 正常（`pypi.org -> 151.101.128.223`），但 TCP 层
  `pypi.org:443` 超时；同为容器的 `www.baidu.com` 22ms、`mirrors.aliyun.com` 21ms、
  `pypi.tuna.tsinghua.edu.cn` 107ms 均通。结论：**容器有网，默认 PyPI 不通**。
- 修复：`Dockerfile` 增加构建参数 `PIP_INDEX_URL`（默认清华镜像，可覆盖），
  `docker-compose.yml` 三个 build 目标同步透传该参数。
- 二次构建：**成功**，约 100 秒。镜像 `campusclaw:latest` 498 MB。

## 二、编排启动

```
docker compose up -d
```

| 服务 | 状态 | 端口 | 内存占用 |
| --- | --- | --- | --- |
| app | Up (healthy) | 0.0.0.0:8080 | 151 MiB |
| worker | Up | — | 122 MiB |
| qdrant | Up | 127.0.0.1:6333 | 80 MiB |
| mcp | Up | 127.0.0.1:8090 | 43 MiB |

- `app` 的健康检查（compose healthcheck，容器内标准库探测 `/health`）通过，
  `worker` 依赖 `service_healthy` 正确等到 app 健康后才启动。
- 卷 `campusclaw_qdrant_data` 已创建；`./data`、`./uploads` 以 bind mount 挂载。

## 三、端点验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 健康 | `GET /health` | `200 {"status":"ok"}` |
| 指标 | `GET /metrics` | `200`，含 `campusclaw_http_requests_total`、耗时 summary 分位、材料数、任务积压等 |
| Qdrant | `GET :6333/collections` | `200 {"result":{"collections":[]},"status":"ok"}`（空卷，符合首次启动） |
| MCP 无令牌 | `POST :8090/mcp` | `401` |
| MCP 错令牌 | `POST :8090/mcp` + `Bearer wrong-token` | `401` |
| MCP 正确令牌 | `POST :8090/mcp` + `Bearer <MCP_AUTH_TOKEN>` | `200`，返回 `serverInfo: {"name":"campus-tools","version":"1.30.0"}` |

## 四、端到端冒烟

| 步骤 | 结果 |
| --- | --- |
| 教师登录 `POST /api/login` | `200`，返回 token 与 `{"role":"teacher","class_id":1}` |
| 材料列表 `GET /api/materials` | `200`，读到宿主机既有数据（`A 班示例讲义`） |
| 上传 `POST /api/materials/upload` | `201 {"material_id":3,"status":"active"}` |
| 关键词检索 `POST /api/search {"mode":"keyword"}` | `200`，命中新上传材料（`material=3 chunk=1`） |
| 混合检索 `POST /api/search {"mode":"hybrid"}` | `503 RETRIEVAL_UNAVAILABLE` —— 未配置嵌入模型时的**既定行为**，非缺陷 |

> 说明：`hybrid`/`vector` 依赖嵌入模型，本环境未配 `EMBEDDING_*`，因此这两种模式
> 明确返回 503 而不是静默降级，属于设计选择；`keyword` 模式不受影响。

## 五、数据持久化

| 项 | 宿主机 | 容器内 `/app/data/app.db` |
| --- | --- | --- |
| 文件大小 | 319,488 字节 | 319,488 字节 |
| 材料表 | — | `(1,'A 班示例讲义') (2,'B 班示例讲义') (3,'Docker 验收样例')` |

容器内写入的 `material_id=3` 在宿主机的 `data/app.db` 中可见，bind mount 生效。

## 六、容器内跑门禁（同一份代码在镜像里复现）

| 门禁 | 命令（容器内） | 结果 |
| --- | --- | --- |
| 密钥扫描 + 依赖基线 | `python scripts/check_security.py` | 绿。真实密钥明文 0 命中；如实标注两项降级：git 不可用（未扫全量历史）、依赖未做在线漏洞库比对 |
| 审计七列回查 | `python scripts/audit_recheck.py --db /app/data/app.db` | 绿。拒绝记录 14 条；表结构断言通过；关联键断言通过（有用户名的记录均带 `actor_id`） |
| 观测告警判定 | `python scripts/check_observe.py --db /app/data/app.db` | 绿。5 条规则，未通过 0，跳过 1（`http_p95_ms` 无样本） |

补充事实：容器内 `audit_events` 共 14 条，均为 `api.request`，例如
`{'ts':'2026-11-12T13:33:36+00:00','action':'api.request','status':201,'actor':'teacher_a','actor_id':1,'request_id':'req-fa3abf53877','path':'/api/materials/upload'}`。
`actor_id=1` 有值，说明上一轮修的「关联键恒空」缺陷在容器里同样成立。

容器内技能调用记录 0 条 —— 本次未触发对话链路，故 `mcp_tool_calls` 为空。
该项不计入「通过」，如实标注。

## 七、本轮新修的缺陷：DEF-05

**现象**：容器长时间运行时，新上传材料若向量索引失败，关键词检索**要等 app 重启**才命中。

**复现（红）**：用旧镜像上传 `material_id=4`，等待 12 秒后
`POST /api/search {"query":"独特词AAA917","mode":"keyword"}` → `200`，命中 **0** 条。

**根因**：`tutor_db.backfill_keyword_ready` 只在 `create_app` 里被调用一次。
索引 worker 失败时只把状态写成 `failed`，不再补建关键词就绪代次，
于是「向量失败 → 关键词兜底」这条自愈路径只在进程启动时存在。

**修法**：`campusclaw/index_worker.py` 在 `_mark_failed` 之后立即调用
`tutor_db.backfill_keyword_ready(conn)`，让兜底在同一个进程内闭合；失败不影响主循环。

**验证（绿）**：重建镜像并重启后上传 `material_id=5`，
`keyword` 检索在第 6 秒即命中 2 条，**全程未重启 app**。

## 八、已知问题（本轮未修，如实记录）

| 编号 | 问题 | 证据 | 影响 | 建议 |
| --- | --- | --- | --- | --- |
| DEF-06 | Qdrant 客户端与服务端小版本跨度过大 | worker 日志：`Qdrant client version 1.19.1 is incompatible with server version 1.15.5` | 当前仅告警，基础读写正常；跨多个小版本后行为无保证 | 二选一：镜像升到与客户端同小版本，或把 `qdrant-client` 降到 1.16.x（小版本差 ≤1）。本轮未改：镜像仓库当时不可达，无法验证新版本可用性 |
| — | `mcp` 未配令牌时 fail-closed | 无令牌启动 → `exit 2`，日志「启动失败：缺少环境变量 MCP_AUTH_TOKEN」 | 属安全设计，非缺陷 | 已把 `restart: unless-stopped` 改为 `on-failure:3`：原配置下 90 秒内重启 12 次刷屏，现在有限次后停在 `Exited(2)`，可直接看出是「没配令牌」 |

## 九、复现命令（照抄即可）

```bash
# 1) 准备（可选）令牌，未配时 mcp 会 fail-closed 不启动
cp .env.example .env   # 填 MCP_AUTH_TOKEN

# 2) 构建并启动
docker compose up -d --build

# 3) 验证
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:6333/collections
docker compose ps

# 4) 容器内跑门禁
docker compose exec app python scripts/check_security.py --out /tmp/sec.json
docker compose exec app python scripts/audit_recheck.py --db /app/data/app.db --out /tmp/audit.md --allow-empty
docker compose exec app python scripts/check_observe.py --db /app/data/app.db --out /tmp/obs.json
```
