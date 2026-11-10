# CampusClaw

班级教学材料管理与可追溯知识库检索系统，附带 AI 解题助手、班级答疑广场与 MCP 工具接入。

一句话概括：**老师把讲义传上来，学生按本班知识库提问，回答里的每一条引用都能点回原文。**

- 材料按班级隔离，跨班访问一律 404，不靠前端隐藏；
- 回答由检索结果驱动，不是模型自由发挥：检索不到就明说没找到，不编造出处；
- **不配置任何模型也能完整跑通**：关键词检索 + 确定性本地流式回退，适合离线演示。

## 功能

| 模块 | 能做什么 |
| --- | --- |
| **材料管理** | 教师上传 `.txt` / `.md`（UTF-8，单文件 ≤ 10 MiB）、改标题、删除；学生只读本班材料，可预览、下载 |
| **知识库检索** | 三种切分策略（`auto` 定长 800/80、`hierarchy` 按 Markdown 标题、`custom` 自定义），三种检索模式（`keyword` / `vector` / `hybrid`）；结果带材料标题、切片序号、字符区间、摘录与下载链接 |
| **解题助手** | 会话式提问，SSE 流式输出；「引导」只给思路、「直接回答」给结论；教师可维护班级提示词与「解题引导」技能；引用挂回材料；会话可删 |
| **班级答疑广场** | 公开问答闭环：提问 → 回复 → 采纳 → 关闭；AI 辅助回答（不推进状态、不计回复数）；优质问答沉淀为 FAQ 并**自动汇总成一份材料进知识库**；教师端统计面板 |
| **MCP 工具接入** | 教师登记 MCP 服务器、连接并发现工具；技能可绑定「工具名@服务器名」；提问时按白名单确定性调用，工具返回经安全清洗后作为数据注入；每次调用留审计 |
| **认证与接口** | Cookie 会话（8 小时、CSRF 保护）+ Bearer 令牌（`/api/*` 通用）；`/openapi.json` 与 `/swagger/index.html` 可直接试调 |

## 技术栈

Python 3.11 / Flask 3.1 / SQLite（含 FTS5 中文二元组切词）/ LangChain（切分、提示词模板、OpenAI 兼容流式调用）/ Qdrant（向量库，可选）/ SSE 流式响应 / 原生 HTML + 内联 CSS（无前端构建步骤）。

依赖用 [uv](https://docs.astral.sh/uv/) 管理：`pyproject.toml` + `uv.lock` 为准，`requirements.txt` 供容器构建。向量检索是可选增强，不装 Qdrant、不配模型时系统照常可用。

---

## 快速开始

### 方式一：uv（推荐）

```bash
git clone https://github.com/Perry-xwr/campus-claw.git
cd campus-claw
uv sync                 # 创建 .venv 并安装锁定版本
uv run python app.py
```

浏览器打开 <http://127.0.0.1:8080/login>，用下面「预置账号」里的任一账号登录。首次启动会自动创建 `data/app.db` 与 `uploads/`，并写入两个班各一份示例讲义。

想用中文检索以外的东西（向量 / 混合检索、真实模型回答），再补两步：

```bash
docker compose up -d qdrant          # 起向量库
uv run python -m campusclaw.index_worker   # 另开一个窗口，跑索引 worker
```

> 国内网络：uv 不读 pip 的 `pip.ini`，需要在 `%APPDATA%\uv\uv.toml`（macOS/Linux 为 `~/.config/uv/uv.toml`）里配镜像，或设环境变量 `UV_DEFAULT_INDEX`。

### 方式二：pip

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Python 3.11 或 3.12 均可（uv 侧锁的是 3.11，容器镜像用 3.12）。

### 方式三：Docker Compose（一条命令起全部服务）

```bash
docker compose up --build -d
docker compose ps           # 等 STATUS 变成 healthy
```

四个容器：

| 服务 | 端口 | 作用 |
| --- | --- | --- |
| `app` | 8080 | gunicorn 单 worker 跑 Flask 应用 |
| `worker` | — | 索引入队、切片、嵌入、清理旧代次 |
| `qdrant` | 127.0.0.1:6333 | 向量库，数据存命名卷 `qdrant_data` |
| `mcp` | 127.0.0.1:8090 | 仓库自带的 MCP 工具服务 |

宿主机 `./data` 与 `./uploads` 直接挂进容器，`docker compose down` 后再 `up` 数据不丢。数据库迁移全部是**增量建表**，四版功能叠加在同一个库上，不需要单独执行迁移脚本。

### 方式四：一键启动脚本（Windows）

```powershell
pwsh -File scripts\start-all.ps1          # 或双击根目录的 start-all.cmd
pwsh -File scripts\stop-all.ps1           # 停止全部
pwsh -File scripts\start-all.ps1 -NoDocker   # 不起 Qdrant 与 worker，只用关键词检索
```

脚本按 **Qdrant → 索引 worker → MCP 服务(8090) → 应用(8080)** 顺序拉起，自动读取根目录 `.env`，日志写到 `.run/logs/`，PID 记在 `.run/pids.json`。解释器优先级：`-Python <路径>` > 项目 `.venv` > 本机 conda 环境。端口冲突、Docker 未启动、缺 `MCP_AUTH_TOKEN` 都会给出提示而不是静默失败。

---

## 预置账号

首次建库时写入，四个账号分属两个班：

| 用户名 | 口令 | 角色 | 班级 | 能做什么 |
| --- | --- | --- | --- | --- |
| `teacher_a` | `TeacherA#2026` | 教师 | A | 上传、改标题、删除、维护提示词与技能、登记 MCP、答疑管理 |
| `student_a1` | `StudentA1#2026` | 学生 | A | 只读本班材料、检索、提问、发答疑 |
| `student_b1` | `StudentB1#2026` | 学生 | B | 同上，只看到 B 班 |
| `teacher_b` | `TeacherB#2026` | 教师 | B | 同 `teacher_a`，作用域为 B 班 |

两个班各有一份示例讲义（正文分别含 `A_ONLY_SEED` / `B_ONLY_SEED`），可以拿来验证隔离：用 `student_a1` 登录看不到 B 班材料；用 `student_b1` 直接访问 A 班材料 ID 会拿到 404。

内置口令是公开的，**只适合本机演示**。对外部署务必设置自己的 `SECRET_KEY` 与四个 `SEED_*_PASSWORD`，并打开 `CAMPUSCLAW_STRICT_CONFIG=1`。

## 配置

`.env` 完全可选，不存在时用内置默认值。需要覆盖就 `cp .env.example .env` 再填。

| 变量 | 作用 | 不填时 |
| --- | --- | --- |
| `SECRET_KEY` | 会话 Cookie 签名密钥 | 用内置开发密钥 |
| `SEED_TEACHER_A_PASSWORD` 等四个 | 预置账号初始口令，UTF-8 8–72 字节 | 用内置测试口令；填了但长度非法则拒绝初始化 |
| `AUTH_COOKIE_SECURE` | HTTPS 部署时置 `true`，Cookie 加 `Secure` | `false` |
| `CAMPUSCLAW_STRICT_CONFIG` | 置 `1` 后缺密钥/口令直接启动失败 | 关闭 |
| `CAMPUSCLAW_PORT` | 仅 Compose 使用，改宿主机映射端口 | `8080` |
| `CHAT_BASE_URL` / `CHAT_MODEL` / `CHAT_API_KEY` | OpenAI 兼容对话服务，供解题助手生成 | 走确定性本地流式回退 |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` | OpenAI 兼容嵌入服务，供向量检索 | 向量/混合检索返回 503，关键词照常 |
| `QDRANT_URL` / `QDRANT_COLLECTION` | 向量库地址与集合名 | `http://127.0.0.1:6333` / `campusclaw_chunks` |
| `CAMPUSCLAW_TUTOR_STUB` | 置 `1` 换成固定响应模型替身 | 关闭 |
| `MCP_AUTH_TOKEN` | 自建 MCP 服务的 Bearer 令牌，两侧必须一致 | mcp-server 拒绝启动 |

两组模型配置各管一条链路、互不影响。配置的 `base_url` 应符合所选 OpenAI 兼容服务及客户端的接口约定；项目不强制所有服务 URL 都以 `/v1` 结尾。每组的 URL、模型名和 API key 同时非空才启用对应链路。示例：

```
CHAT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
CHAT_MODEL=qwen-plus
CHAT_API_KEY=sk-...

EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_KEY=sk-...
```

口令只在空库初始化时写入，**建库后再改环境变量不会自动更新既有账号**。不要删除 `data/` 来改口令，这会删除数据库及其业务数据。应使用项目支持的账号管理流程更新口令；若当前版本未提供该流程，先在受控备份和维护方案下处理，不要直接清空数据目录。

---

## 使用指南

### 教师：把材料变成可检索的知识库

1. `/materials` 上传 `.txt` 或 `.md`。上传成功（201）只代表文件入库，**索引是否就绪是另一个状态**，看 `/api/materials/{id}/index-status` 的 `ready`。
2. 索引由后台 worker 完成。切分策略可选：`auto`（定长 800 字、重叠 80）、`hierarchy`（按 `#` 标题切）、`custom`（自定义块大小、重叠比例、分隔符）。
3. 重建索引用 `POST /api/materials/{id}/reindex`，例如 `{"strategy":"hierarchy"}`。重建会写新代次，旧代次由 worker 清理，检索只命中生效代次。
4. `/knowledge` 页可以直接试检索，三种模式对比效果。

### 学生：带着引用问问题

1. `/tutor` 新建会话，连续追问（每次带最近 6 条历史）。
2. 回答前先检索本班知识库：配了嵌入走 `hybrid`，没配回落 `keyword`，实际链路在 SSE `meta.retrieval_mode` 里标明。
3. 输入框上方可切换「引导 / 直接回答」。引导只给思路与第一步，适合练习；直接回答给结论与数量，适合核对。
4. 每条回答下面的 `[编号]` 引用能点回材料，带标题、切片号、字符区间。

### 答疑广场：把一次问答沉淀成班级资产

- `/qa` 广场列表，支持按状态、排序、分页筛选；`/qa/questions/{id}` 详情页发回复、发起 AI 辅助、教师采纳/关闭。
- 状态流转 `OPEN → ANSWERED → ACCEPTED → CLOSED`，另有 `accepted_reply_id` / `resolved_at` 等标记字段。**统计按字段算而不是按状态值算**，所以「采纳后被关闭」不会丢解决记录，且 `待解决 + 已解决 + 已关闭未采纳` 恒等于问题总数。
- AI 辅助回答单独存表，**不推进状态、不计入回复数**，避免把机器答案混进人工服务量。
- 教师可从问答生成 FAQ 草稿，发布后系统会把本班 FAQ 汇总成一份真实 `.md` 材料写进上传目录，走既有索引入队流程——所以引用链接指向的是可下载的真实材料，不是虚拟条目。

### MCP：让助手真的会算、会换算

- `mcp-server/` 是仓库自带的工具服务：两个演示工具 `formula_hint`（按关键词给解题步骤提示，不给最终答案）与 `unit_convert`（米↔厘米、千克↔克）。
- 启动：`MCP_AUTH_TOKEN=你的令牌 uv run python -m mcp_server`（在 `mcp-server/` 目录下执行），或由 Compose 一并启动。
- 教师进 `/mcp` 登记服务器（名称 / Base URL / 令牌），点「连接并发现」做握手与 `tools/list`。令牌只存在服务端，接口只回 `has_auth`。
- 在技能的「工具」栏写「工具名@服务器名」，保存前过四道校验（格式 → 服务器属本班 → 已连接 → 工具在缓存清单内），任一不过整份拒绝。
- 命中技能后**先调工具、再生成**：调用哪些、传什么参由服务端按白名单决定，不依赖模型原生 function calling；工具返回若命中「忽略前述」类句式或超 1200 字，整条丢弃。

## 页面与接口

| 页面 | 路径 | 谁能进 |
| --- | --- | --- |
| 登录 | `/login` | 所有人 |
| 材料管理 | `/materials` | 本班师生（教师可写） |
| 知识检索 | `/knowledge` | 本班师生 |
| 解题助手 | `/tutor` | 学生、教师 |
| 助手设置（提示词 / 技能） | `/tutor/settings` | 仅教师 |
| MCP 管理 | `/mcp` | 仅教师 |
| 答疑广场 | `/qa`、`/qa/questions/{id}`、`/qa/faq` | 本班师生 |
| 答疑统计 | `/qa/stats` | 仅教师 |
| Swagger 试调 | `/swagger/index.html`、`/openapi.json` | 登录后 |
| 健康检查 | `/health` | 免登录 |

接口分四组，全部按班级边界过滤，跨班与不存在统一返回 404：

- `/api/materials/*`、`/api/search`、`/api/ask` —— 材料与检索；
- `/api/prompt`、`/api/skills/*`、`/api/conversations/*` —— 提示词、技能、会话与流式消息；
- `/api/mcp/*` —— 服务器登记、连接、工具清单、调用审计；
- `/api/qa/*` —— 问题、回复、采纳、关闭、FAQ、统计。

认证两种方式：

```bash
# Bearer 令牌：先换令牌，再带 Authorization 头
curl -X POST http://127.0.0.1:8080/api/login \
     -H "Content-Type: application/json" \
     -d '{"username":"teacher_a","password":"TeacherA#2026"}'

curl http://127.0.0.1:8080/api/search \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"query":"示例讲义","mode":"keyword","limit":5}'
```

Cookie 会话的写请求仍然必须带 `X-CSRF-Token`；Bearer 令牌的写请求免 CSRF。

## 目录结构

```
app.py                     启动入口，打印账号横幅
campusclaw/                应用包
  config.py                配置、内置测试默认值、严格模式
  db.py / bootstrap.py     SQLite 连接、建表、空库单事务初始化
  security.py / sessions.py  bcrypt 哈希、sid、CSRF、可撤销会话
  storage.py               私有上传目录、清理任务、启动恢复
  materials.py             材料查询、上传、改标题、删除
  chunking.py              三种切分策略与字符区间校验
  retrieval*.py            检索表与 FTS5、关键词/向量/混合检索
  index_worker.py          后台切片、嵌入、旧代次清理
  tutor*.py                提示词组装、技能解析、流式生成
  mcp_*.py                 MCP 登记、传输客户端、引用四道校验、调用编排
  qa_*.py                  答疑广场数据层与 FAQ 材料化
  openapi.py               OpenAPI 3 文档生成
  views/                   页面与 API 蓝图
  templates/               页面模板（样式内联，无静态资源依赖）
mcp-server/                自建 MCP 工具服务（FastMCP + Bearer 门禁）
scripts/                   启动/停止脚本、自检、文件清理
Dockerfile / docker-compose.yml
pyproject.toml / uv.lock / requirements.txt
```

## 自检

```bash
uv run python scripts/selfcheck.py
```

不改动项目数据：在临时目录起一个服务，依次登录四个账号，核对健康检查、登录跳转、材料数与班级隔离，跑完自动清理，退出码 0 表示环境可用。换机器、换 Python 版本、升级依赖之后先跑它。

### 异步批改

`POST /api/submissions` 接收作业并返回 `202` 与任务 ID；通过 `GET /api/tasks/{task_id}` 查询状态。独立消费者可常驻运行，或使用 `--once` 执行当前可领取队列：

```bash
uv run python -m campusclaw.task_worker
uv run python -m campusclaw.task_worker --once
```

三项隔离判据使用本地确定性 stub，不需要模型 API，也不操作项目 `data/`：

```bash
uv run python scripts/acceptance_async.py
```

Windows 可运行 `pwsh -File scripts/check-all.ps1 -Mode async`。该脚本验证异步队列的提交响应、消费者恢复和重复投递幂等性，不替代 `docs/requirements/acceptance-scenarios.md` 中的 37 个业务场景。历史运行输出保存在 `reports/evidence/async-acceptance.json`，该文件记录一次具体运行结果，不会随脚本运行自动覆盖，除非显式传入 `--out`。

## 常见问题

**Docker 报 `failed to fetch oauth token`。** 不是代码问题，是 Docker 守护进程拉不到 `python:3.12-slim`。在 Docker Desktop → Settings → Docker Engine 里配 `registry-mirrors`，或在 Resources → Proxies 里给 Docker 配本机代理，Apply & restart。实在不行就用方式一/二本地跑，关键词检索不依赖 Docker。

**配了模型但检索还是失败。** 检查 URL 是否符合所选兼容服务要求、该组 URL/模型/key 是否均配置，以及索引是否已就绪（`index-status` 的 `ready`）。换嵌入模型可能带来向量维度变化，Qdrant 会报 `vector dimension differs`；确认旧集合数据处置方案后再配置新的 `QDRANT_COLLECTION` 并重建索引。

**零模型环境下演示答疑 FAQ。** 发布 FAQ 后本班检索要等 worker 建索引；时间紧就重启一次应用，启动时会补建关键词切片。

**流式回答变成一次性整段到达。** 中间有会缓冲的代理。响应已带 `X-Accel-Buffering: no`，还需在 nginx 侧关掉缓冲。

**改了 `SEED_*_PASSWORD` 但口令没变。** 口令只在空库初始化时写入，已有账号不会因环境变量变化而更新。不要删除 `data/`；请使用账号管理流程或经过备份与审核的数据维护步骤修改。

**端口 8080 被占。** `CAMPUSCLAW_PORT=8090 docker compose up -d`，或 `pwsh -File scripts/start-all.ps1 -AppPort 8099 -McpPort 8091`。

## 已知限制

- 只支持单个 UTF-8 编码的 `.txt` / `.md`，≤ 10 MiB；不做 PDF/Word/图片解析、OCR、批量上传、断点续传、版本覆盖。
- 单机单 worker 的演示架构，不提供高并发与高可用保证；gunicorn 固定单 worker。
- 会话取最近 6 条历史进入提示词，不做跨会话长期记忆。
- 答疑广场的问题不可编辑与删除（只能关闭），不支持附件、@提醒、点赞、通知，FAQ 只在班内可见。
- MCP 演示工具只覆盖两类语义，取参规则是「提问原文进 query 类键、其余参数由代码给定」，不实现模型原生 function calling。
- mcp-server 使用 MCP 流式 HTTP 的默认 SSE 响应（开 `json_response` 会让官方客户端 `tools/call` 失败），裸 curl 断言时需解析 `data:` 行。
- 内置演示凭据是公开信息，仅供本机演示；对外部署必须替换并开启严格模式。
