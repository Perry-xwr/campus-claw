# 异步作业批改队列：把「请求内批改」改为「任务记录 + 独立消费者」

## Why

第 8 课《异步任务与消息队列》要求把同步批改改成异步执行，并用三条判据验收：① 提交接口 P95 显著小于一次批改执行时间且不随批改耗时增加而延长、响应体不含评分结果；② 停消费者后提交仍成功、状态停留 `pending`，恢复后自动执行无需重新提交；③ 同一提交重复发送或同一消息重复投递，最终只产生一份结果，`attempts` 递增而结果不变。

本项目此前**没有作业批改业务**，只已有一条异步索引链路（`index_jobs` + `index_worker` + `POST /api/materials/{id}/reindex` 返回 202 + `job_id`），不存在可改造的「同步批改」代码路径。因此本变更按课件语义**新建一套独立的等价异步批改链路**，而不是改造既有链路：既能完整覆盖五步实施顺序与三条判据，又不会给已上线的索引链路带来回归。取舍理由与逐项映射见下文与 [design.md](./design.md)。

## What Changes

- 新增独立的异步批改链路，全部为新增能力，主 spec 既有 6 个能力一律不改动：
  - `campusclaw/task_db.py`：表结构与数据访问，三张表 `grade_submissions`、`grade_tasks`、`grade_results`；建表用 `CREATE TABLE IF NOT EXISTS`，迁移可重复执行。
  - `campusclaw/views/task_views.py`：`POST /api/submissions`（学生可写，`require_write_any`）返回 202 与任务标识；`GET /api/tasks/<task_id>`（`require_api_auth`，只读）。
  - `campusclaw/task_worker.py`：独立消费者进程 `python -m campusclaw.task_worker [--once]`。
  - `scripts/acceptance_async.py`：三条判据复现；`scripts/check_security.py`：SEC-05/06 扫描；`Makefile`：一键 `make check-security`。
  - `AGENTS.md`、`docs/AI代码审核评审表.md`、`reports/*.md`：阶段重点与安全自查交付物。
- 三张表的关键约束：`grade_submissions` 有 `UNIQUE(class_id,user_id,assignment_ref,content_hash)`；`grade_tasks` 有 `task_id TEXT UNIQUE`、`idempotency_key TEXT UNIQUE`、`status CHECK IN ('pending','running','succeeded','failed','dead')`、`attempts`、`max_attempts`、`error`、`error_kind('transient','permanent')`、`next_retry_at`、`started_at`、`finished_at`、`created_at`、`updated_at`；`grade_results` 有 `idempotency_key TEXT UNIQUE`。
- 幂等键固定为 `grade:<submission_id>:v1`，由业务含义派生（含版本与内容标识），不随机；重复提交同一份内容返回同一个 `task_id`；重复投递写结果用 `INSERT OR IGNORE` 靠唯一约束吸收，去重不靠「先查一遍」。
- 事务性发件箱：提交记录与任务记录必须在同一个 `BEGIN IMMEDIATE ... COMMIT` 里写入，不允许「先写提交、再补任务」的两次提交。
- 消费者用 `BEGIN IMMEDIATE` 认领实现竞争消费与至少一次语义；零模型环境下用确定性本地批改，耗时由环境变量 `CAMPUSCLAW_TASK_DELAY_MS` 外置配置；失败分类、指数退避加 jitter、达到 `max_attempts` 转 `dead` 并保留失败原因。
- 班级隔离：任务与结果都按 `class_id` 过滤，跨班与不存在统一 404；接口响应不含分数。
- 安全自查与证据归档：SEC-01~07 三段式（前置条件 / 操作 / 可观测结果 + 当前实际 + 当前判定），本课只记录现象不提前修复（密钥明文命中除外），至少留 1 条红；`reports/` 固定文件名；并发与事务两条按四段写全；四份变更文件与 git tag；README 注明入口。
- AI 代码审核：七类拆解核查清单落进 Harness 规则与 `AGENTS.md`；七维度 + 三分法（可用 / 待修改 / 风险无效）评审表归档 `docs/`；批量扫描固定为检查步骤；准入流程 AI 初稿 → 自审 → 交叉评审 → 合入 main，未审核不得合入。

### 课件语义到本变更的映射

本项目没有「同步批改」可改，故按课件的验收语义新建等价链路，逐项映射如下：

| 课件概念 / 步骤 | 本变更落点 |
| --- | --- |
| 同步批改接口 | 本项目原无该接口；新建 `POST /api/submissions` 作为等价提交入口 |
| ① 编排文件新增队列服务且配置外置 | 不新增独立 broker 服务；以 `Makefile` 登记消费者进程的独立启停入口，应用初始化处注册 `task_views` 蓝图并调用 `task_db.ensure_schema`；耗时参数 `CAMPUSCLAW_TASK_DELAY_MS` 外置，数据库路径沿用 `CAMPUSCLAW_HOME` 等既有配置入口 |
| ② 任务记录（幂等键唯一约束、迁移可重复执行） | `grade_tasks` 表 + `idempotency_key TEXT UNIQUE` + `CREATE TABLE IF NOT EXISTS` |
| ③ 提交接口返回 202 + 任务标识 | `POST /api/submissions` 返回 `{"task_id","status":"pending","status_url":"/api/tasks/<task_id>"}`，响应不含分数，代码库不再有请求内调用模型的分支 |
| ④ 独立消费者进程 | `python -m campusclaw.task_worker [--once]`，取消息、批改、写回、确认，可独立启停 |
| ⑤ 状态接口与重试 | `GET /api/tasks/<task_id>` 只读；`attempts`/`max_attempts`/指数退避+jitter/死信保留失败原因 |
| 队列 / broker | 用 `grade_tasks` 表实现队列语义（课件 `queue.html` 明确允许「不用消息队列、用数据库任务表 + 定时扫描」达到三条判据） |
| 模型调用 | 零模型环境下确定性本地批改 + `CAMPUSCLAW_TASK_DELAY_MS` 演示耗时 |

## Capabilities

### New Capabilities

- `async-grading-queue`：新建的异步作业批改链路——提交接口 202、独立消费者、只读状态接口、事务性发件箱、幂等去重、失败重试与死信，以及三条判据复现。
- `security-precheck`：SEC-01~07 三段式安全自查、固定文件名的 `reports/` 归档、并发与事务复核、一键 `make check-security` 覆盖 SEC-05/06、README 入口与 git tag。
- `ai-code-review`：七类拆解核查清单、七维度三分法评审表、批量扫描固定检查步骤，以及 AI 初稿 → 自审 → 交叉评审 → 合入 main 的准入流程。

## Impact

- 新增文件（严格限本次交付范围）：`campusclaw/task_db.py`、`campusclaw/task_worker.py`、`campusclaw/views/task_views.py`、`scripts/acceptance_async.py`、`scripts/check_security.py`、`Makefile`、`AGENTS.md`、`docs/AI代码审核评审表.md`、`reports/*.md`。
- 少量接入改动：`campusclaw/__init__.py` 在 `prepare_storage_and_db` 增加 `task_db.ensure_schema(conn)`、在 `create_app` 注册 `task_views` 蓝图；README 注明 `make check-security` 与 `reports/` 入口。以上改动只做「注册」，不改既有索引链路的任何逻辑。
- 数据库：新增三张表，均为幂等增量建表，对既有表、账号、材料与知识索引无破坏；重复启动不报错。
- 既有索引链路（`index_jobs`、`index_worker`、`POST /api/materials/{id}/reindex`、返回 202 + `job_id`）保持原样，不复用、不改名、不回归。
- 依赖：不引入新 Python 依赖；不引入独立 broker；`grade_tasks` 表承担队列语义。
- OpenSpec：本变更为纯新增能力，全部使用 `## ADDED Requirements`；不修改 `openspec/specs/` 下的 6 个主 spec，不归档本变更。

## Non-goals

- 不改既有索引链路：`index_jobs`、`index_worker`、`POST /api/materials/{id}/reindex` 及其 202 + `job_id` 行为全部保持原样。
- 不引入新 Python 依赖：仅用标准库与项目既有 Flask / SQLite 设施。
- 不引入独立 broker（RabbitMQ / Redis / Celery 等）：用 SQLite 任务表实现队列语义，课件 `queue.html` 明确允许「不用消息队列、用数据库任务表 + 定时扫描」达到三条判据。
- 不改动既有同步业务（本项目本就没有同步批改）；不把 `POST /api/materials/{id}/reindex` 改造成批改入口。
- 不做真实模型调用：零模型环境下用确定性本地批改，耗时由 `CAMPUSCLAW_TASK_DELAY_MS` 演示。
- 本课安全自查只记录现象、不提前修复（密钥明文命中除外），并至少保留 1 条红；不做其它课程范围的安全补强。
- 不修改 `openspec/specs/` 下的主 spec，不归档本变更，不改动其它目录。

## 验收基线与证据约定

1. 验收在独立测试数据目录运行（`CAMPUSCLAW_HOME` 指向隔离目录），使用有效登录态；写请求按认证方式携带 CSRF（仅 Cookie 会话需要）。
2. 三条判据用 `scripts/acceptance_async.py` 复现；停/启消费者用 `python -m campusclaw.task_worker [--once]` 控制；批改耗时用 `CAMPUSCLAW_TASK_DELAY_MS` 调整两档对比。
3. 每场景取证：H 为脱敏 HTTP 请求 / 状态码 / 响应；D 为数据库前后记录；F 涉及文件时记录内容与 SHA-256。口令、令牌、CSRF 一律遮盖；本文件不预填通过。
4. 班级隔离判定：跨班访问与「没有这条数据」表现一致（统一 404），不得可区分。
5. 证据归档：`reports/` 下固定产出 `security-precheck.md`、`risk-authz.md`、`risk-concurrency.md`、`risk-transaction.md`、`security-baseline.md`、`review-01.md` 与三条判据复现记录；并发与事务两条按「用什么手段查 / 查了什么 / 判据 / 结果」写全；变更交付 `proposal.md`、`design.md`、`tasks.md`、`specs/` 四份文件；打 git tag（标签名按交付时约定）。
6. 一键 `make check-security` 覆盖 SEC-05/06；README 注明该入口与 `reports/` 报告的查看方式。
