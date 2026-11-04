# 技术方案：异步作业批改队列（第 8 课）

## Context

本变更是「互联网软件开发技术与实践」第 8 课《异步任务与消息队列》的作业交付物之一。业务范围以 [proposal.md](./proposal.md) 为权威输入，业务验收条款见同变更 `specs/` 下三份 delta spec，实施顺序见 [tasks.md](./tasks.md)。

课件原要求把「同步批改」改成异步执行。但本项目此前没有作业批改业务，已有的是异步索引链路（`index_jobs` + `index_worker` + `POST /api/materials/{id}/reindex` 返回 202 + `job_id`）。因此本次按课件语义**新建一套独立的异步批改能力**，不改动既有索引链路，避免回归。取舍与逐项映射见 [proposal.md](./proposal.md)「课件语义到本变更的映射」。课件 `queue.html` 明确允许「不用消息队列、用数据库任务表 + 定时扫描」达到三条判据，故本变更不引入独立 broker，用 `grade_tasks` 表实现队列语义。

实现体例沿用项目既有设施：`campusclaw/__init__.py` 的 `prepare_storage_and_db`（幂等增量建表）与 `create_app`（注册蓝图）、`require_write_any` / `require_api_auth` 权限链、`ApiError` 统一错误体、SQLite 显式 `BEGIN IMMEDIATE / COMMIT / ROLLBACK`、`sqlite3.Row` 字典化、UTC ISO 8601 时间戳。不引入新 Python 依赖。

## Goals

- G1 新建三张表与数据访问层 `campusclaw/task_db.py`，迁移可重复执行，唯一约束与 CHECK 生效。
- G2 `POST /api/submissions` 在同一事务内写提交与任务并返回 202 + `task_id`，响应不含分数；代码库无请求内调用模型的分支。
- G3 独立消费者 `python -m campusclaw.task_worker [--once]`：`BEGIN IMMEDIATE` 认领、确定性本地批改、写回结果、确认、可独立启停。
- G4 `GET /api/tasks/<task_id>` 只读、按 `class_id` 隔离、跨班与不存在统一 404；可观测字段齐备。
- G5 幂等去重落在写结果的唯一约束上；失败分类、指数退避 + jitter、达到 `max_attempts` 转 `dead` 并保留失败原因。
- G6 三条判据可离线复现；`reports/`、四份变更文件、git tag、`make check-security`、README 入口齐备。

## Non-Goals

- 不改动既有索引链路（见 Context）；不引入独立 broker；不引入新 Python 依赖；不做真实模型调用。
- 安全自查本课只记录现象、不提前修复（密钥明文命中除外），至少留 1 条红。
- 不修改 `openspec/specs/` 下的主 spec；不归档本变更。

## 1. 架构决策

### 1.1 关键决策与理由

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 业务落点 | 新建独立异步批改链路，不改 `index_jobs` / `index_worker` / `POST /api/materials/{id}/reindex` | 本项目无同步批改可改；新建可完整覆盖五步与三条判据，且对已上线索引链路零回归 |
| 队列实现 | SQLite `grade_tasks` 表 + 独立消费者进程 | 课件 `queue.html` 允许「数据库任务表 + 定时扫描」；避免引入 broker 与部署复杂度 |
| 编排与配置 | `Makefile` 登记消费者启停入口；耗时参数 `CAMPUSCLAW_TASK_DELAY_MS` 外置；数据目录沿用 `CAMPUSCLAW_DATA_DIR` 等既有配置 | 配置外置、不写死；不新增 compose 队列服务 |
| 模型调用 | 零模型环境确定性本地批改 + 可配置延迟 | 无外部模型依赖即可复现「提交快、批改慢」的判据一 |
| 去重落点 | `INSERT OR IGNORE` + `grade_results.idempotency_key` 唯一约束 | 去重必须落在「写入结果」的语句上，不能靠「先查一遍」 |
| 并发控制 | `BEGIN IMMEDIATE` 认领 | 竞争消费只认领一次，配合至少一次投递语义 |

### 1.2 分层与文件

```
学生 / 客户端
   │ POST /api/submissions（require_write_any）
   │ GET  /api/tasks/<task_id>（require_api_auth，只读）
   ▼
campusclaw/views/task_views.py     提交接口 / 状态接口
   │ 同一事务写两行；按 class_id 过滤
   ▼
campusclaw/task_db.py              grade_submissions / grade_tasks / grade_results
   ▲ 读写                            ▲ 唯一约束 / CHECK / 索引
   │                                │
   └──────── 独立消费者进程 ──────────┘
        campusclaw/task_worker.py（python -m campusclaw.task_worker [--once]）
        BEGIN IMMEDIATE 认领 → 确定性批改 → INSERT OR IGNORE 写结果 → 确认/重排

scripts/acceptance_async.py   三条判据复现
scripts/check_security.py     SEC-05/06 扫描（由 make check-security 一键调用）
Makefile / AGENTS.md / docs/AI代码审核评审表.md / reports/*.md   交付与证据
```

接入改动仅限注册：`campusclaw/__init__.py` 的 `prepare_storage_and_db` 增 `task_db.ensure_schema(conn)`、`create_app` 注册 `task_views` 蓝图；README 注明入口。

## 2. 数据模型

### 2.1 表结构（DDL 摘要，均在 `task_db.ensure_schema` 内幂等执行）

| 表 | 字段与约束 |
| --- | --- |
| `grade_submissions` | `id` PK；`class_id` NOT NULL；`user_id` NOT NULL；`assignment_ref` NOT NULL；`content` NOT NULL；`content_hash` NOT NULL；`created_at` NOT NULL；`UNIQUE(class_id,user_id,assignment_ref,content_hash)` |
| `grade_tasks` | `id` PK；`task_id TEXT UNIQUE` NOT NULL；`submission_id` NOT NULL；`class_id` NOT NULL；`user_id` NOT NULL；`idempotency_key TEXT UNIQUE` NOT NULL；`status` NOT NULL `CHECK(status IN ('pending','running','succeeded','failed','dead'))` DEFAULT `'pending'`；`attempts` NOT NULL DEFAULT 0；`max_attempts` NOT NULL；`error` TEXT；`error_kind` TEXT `CHECK(error_kind IN ('transient','permanent'))`；`next_retry_at` TEXT；`started_at` TEXT；`finished_at` TEXT；`created_at` NOT NULL；`updated_at` NOT NULL |
| `grade_results` | `id` PK；`idempotency_key TEXT UNIQUE` NOT NULL；`submission_id` NOT NULL；`task_id` NOT NULL；`score`；`feedback`；`created_at` NOT NULL |

三张表均用 `CREATE TABLE IF NOT EXISTS` 建立，索引与约束随建表语句一次性声明，迁移可重复执行、对既有 `data/app.db` 无破坏。时间戳统一 UTC ISO 8601，与项目既有时间工具同格式。

### 2.2 幂等键

- 格式固定 `grade:<submission_id>:v1`：由业务含义派生，含版本（`v1`）与提交标识（`submission_id`），`submission_id` 又由同一份内容经 `content_hash` 与 `UNIQUE(class_id,user_id,assignment_ref,content_hash)` 稳定确定；**不使用随机值**。
- 重复提交同一份内容 → 命中 `grade_submissions` 唯一约束 → 复用同一 `submission_id` 与同一 `task_id` → 返回同一个 `task_id`，不新增任务行。
- `grade_results.idempotency_key` 与任务同源；重复投递写结果时用 `INSERT OR IGNORE`，由该列的唯一约束吸收，结果行数恒为 1。

## 3. 事务性发件箱

`POST /api/submissions` 的写入路径是单个显式事务：

```
BEGIN IMMEDIATE
  INSERT INTO grade_submissions (...)          -- 命中唯一约束时复用既有行
  INSERT INTO grade_tasks (... idempotency_key = 'grade:<submission_id>:v1', status='pending')
COMMIT
```

- 提交记录与任务记录 **MUST 在同一事务**；任一步失败整体 `ROLLBACK`，不允许出现「有提交无任务」的半写入。
- 接口在事务提交成功后立即返回 202，不等待批改；响应体只含 `{"task_id","status":"pending","status_url":"/api/tasks/<task_id>"}`，不含 `score` / `feedback`。
- 课件要求的「配置外置」落在 `CAMPUSCLAW_TASK_DELAY_MS`（批改耗时）与 `CAMPUSCLAW_DATA_DIR` 等既有数据目录配置上，代码不写死耗时与绝对路径。

## 4. 接口契约

| # | 方法与路径 | 权限 | 成功响应 | 说明 |
| --- | --- | --- | --- | --- |
| T-001 | `POST /api/submissions` | `require_write_any`（学生可写） | 202 `{"task_id","status":"pending","status_url":"/api/tasks/<task_id>"}` | 同事务写提交 + 任务；响应不含分数 |
| T-002 | `GET /api/tasks/<task_id>` | `require_api_auth`，只读 | 200 状态 + `attempts` + 时间戳 + `result` | 不触发执行、不写库；按 `class_id` 过滤 |

- `class_id` / `user_id` 一律取自登录会话，不从请求体读；请求体带身份字段一律 400。
- 跨班任务与不存在的 `task_id` 统一 404，状态码、错误码、响应体完全一致，不可区分。
- 状态接口返回的可观测字段：`status`、`attempts`、`max_attempts`、`error`、`error_kind`、`next_retry_at`、`started_at`、`finished_at`、`created_at`、`updated_at`，以及在有结果时的 `result`（`score` / `feedback`）。
- 代码库不再保留「请求内调用模型」的分支：`POST /api/submissions` 只做写库与返回，`GET /api/tasks/<task_id>` 只读。

## 5. 任务状态机

```
                    ┌──────────── 认领（BEGIN IMMEDIATE）────────────┐
                    ▼                                               │
  pending ──────► running ──► succeeded ──► (终态)                  │
     ▲                │                                              │
     │                ├─► failed ──► next_retry_at 到期后重新可认领 ───┘
     │                │              （attempts 每次递增，指数退避 + jitter）
     │                └─► dead ──► (终态，保留 error / error_kind)
     │                       ▲
     └───────────────────────┘（仅经消费者认领转换；接口不推进状态）
```

- 合法取值固定为 `pending` / `running` / `succeeded` / `failed` / `dead`，由 `CHECK` 约束保证。
- 提交产生 `pending`；消费者 `BEGIN IMMEDIATE` 认领置 `running` 并写 `started_at`、`attempts += 1`。
- 成功写 `grade_results`（`INSERT OR IGNORE`）后置 `succeeded` 并写 `finished_at`。
- 失败写 `error` 与 `error_kind`，置 `failed`；按退避算 `next_retry_at` 等待再次认领；达到 `max_attempts` 转 `dead`，**保留失败原因**，不再被自动认领。
- `permanent` 失败不重试，直接进终态；`transient` 失败才有退避与次数上限逻辑。

## 6. 消费者、至少一次投递与竞争消费

- 启动：`python -m campusclaw.task_worker [--once]`；`--once` 跑完当前可认领的一批即退出，便于复现与批量验收；不带参数则持续扫描。进程可独立启停。
- 认领：`BEGIN IMMEDIATE` 选出一条可执行的 `pending`（或重试到期）任务并置 `running`，事务提交后才开始批改。SQLite 的写锁保证两个消费者并发扫描时只有一个拿到该任务，另一个不会重复执行批改。
- 投递语义：**至少一次**。任务可能在确认前被重复投递，因此结果写入必须幂等（见 2.2 与 3 节）；`attempts` 如实递增记录重复投递，`grade_results` 始终只有一行且 `score` / `feedback` 不变。
- 批改：零模型环境下用确定性本地批改（同一内容恒得同一结果），耗时由 `CAMPUSCLAW_TASK_DELAY_MS` 演示，用于判据一中「批改耗时变化而提交 P95 不变」的对比。
- 确认：写结果与置 `succeeded` 在消费者侧完成后才算消息确认；失败则按第 7 节分类处理。

## 7. 幂等与唯一约束、去重落点

1. **提交去重**：`grade_submissions` 的 `UNIQUE(class_id,user_id,assignment_ref,content_hash)` + 由内容派生的 `content_hash`。同一份内容重复发送返回同一个 `task_id`，不新增提交行与任务行。
2. **任务去重**：`grade_tasks.task_id TEXT UNIQUE` 与 `grade_tasks.idempotency_key TEXT UNIQUE` 保证一个提交只对应一条任务。
3. **结果去重（关键）**：写结果的语句必须是 `INSERT OR IGNORE INTO grade_results (...)`，靠 `grade_results.idempotency_key TEXT UNIQUE` 吸收重复投递；**不得**用「先 SELECT 查一遍是否存在、再决定 INSERT」实现去重。该约束是判据三的最终保证。
4. 幂等键由业务含义派生，非随机；版本位 `v1` 使将来批改逻辑升级可显式换键。

## 8. 失败分类、退避与死信

- 失败分类：批改异常按 `error_kind` 分为 `transient`（可重试，如临时故障 / 超时）与 `permanent`（不可重试，如内容不合法）。分类结果写入任务行，`error` 保留可读失败原因（不含凭据与堆栈）。
- 退避：`transient` 失败按 `attempts` 指数增长设置 `next_retry_at`，并叠加随机 jitter，避免多任务同一刻重试造成惊群；不是固定间隔。
- 次数上限：`attempts` 每次认领递增，达到 `max_attempts` 后 `status` 转 `dead`，保留最后一次 `error` / `error_kind`，不再被自动认领，也不凭空生成结果。`permanent` 失败直接进终态且 `next_retry_at` 为空。
- 可观测：死信数 = `SELECT COUNT(*) FROM grade_tasks WHERE status='dead'`，可按班过滤；`started_at` / `finished_at` / `attempts` / `next_retry_at` 共同支撑「任务卡在哪一步」的判读。

## 9. 只读状态接口

- `GET /api/tasks/<task_id>` 只做 `SELECT`，**不触发执行、不写库**：查询前后 `grade_tasks` 与 `grade_results` 行数不变，`attempts` 不变。
- 状态接口与消费者解耦：消费者停止时状态保持 `pending`；恢复后由消费者自行认领，状态接口无需、也不会重新提交。
- 班级隔离在 SQL 层按 `class_id` 过滤，跨班与不存在统一 404。

## 10. 三条判据如何复现

由 `scripts/acceptance_async.py` 在独立测试数据目录复现，证据写入 `reports/`：

1. **判据一（P95 与批改耗时解耦、响应不含分数）**：把 `CAMPUSCLAW_TASK_DELAY_MS` 设为较小 / 较大两档，各重复提交多次 `POST /api/submissions`，统计 P95；断言两档 P95 均显著小于对应批改耗时，且大耗时档 P95 不随耗时增加而延长；断言每次 202 响应体不含 `score` / `feedback`；核对 `grade_tasks` 在提交瞬间为 `pending`。
2. **判据二（停消费者仍可提交、恢复自动执行）**：停止消费者进程 → 提交 → 反复查询 `GET /api/tasks/<task_id>` 断言停留 `pending`、`grade_results` 无行 → 启动 `python -m campusclaw.task_worker --once` → 断言无需重新提交即自动推进到 `succeeded`，且只新增一行结果。
3. **判据三（重复提交 / 重复投递只有一份结果）**：同一内容重复 `POST /api/submissions` 断言返回同一 `task_id`、D 无新增行；模拟同一消息重复投递断言 `INSERT OR IGNORE` 被唯一约束吸收，`grade_results` 仍一行且分数不变、`attempts` 递增。

## 11. 与既有索引链路的边界

| 维度 | 既有索引链路（不动） | 本次新建批改链路 |
| --- | --- | --- |
| 表 | `index_jobs` 等既有表 | `grade_submissions` / `grade_tasks` / `grade_results` 三张新表 |
| 进程 | `campusclaw/index_worker.py` | `campusclaw/task_worker.py` |
| 入口 | `POST /api/materials/{id}/reindex`（202 + `job_id`） | `POST /api/submissions`（202 + `task_id`）、`GET /api/tasks/<task_id>` |
| 视图 | `campusclaw/views/retrieval_views.py` | `campusclaw/views/task_views.py` |

两者不共用表、不共用进程、不共用接口前缀；`campusclaw/__init__.py` 仅新增一条 `ensure_schema` 与一次蓝图注册，不改动既有索引链路的任何语句、状态机或响应体。

## 12. 证据归档、安全自查与 AI 代码审核

### 12.1 变更与证据文件

- 变更四份文件：`proposal.md`、`design.md`、`tasks.md`、`specs/`（三份 delta spec）；交付时打 git tag（标签名按交付时约定）。
- `reports/` 固定文件名：`security-precheck.md`、`risk-authz.md`、`risk-concurrency.md`、`risk-transaction.md`、`security-baseline.md`、`review-01.md`，以及三条判据复现记录。
- 每场景取证 H（脱敏 HTTP 请求 / 状态码 / 响应）、D（数据库前后记录）、F（文件内容与 SHA-256）；口令、令牌、CSRF 一律遮盖；不预填通过。
- 并发与事务两条按「用什么手段查 / 查了什么 / 判据 / 结果」四段写全，结果如实记录。

### 12.2 安全自查（SEC-01~07）

- `reports/security-precheck.md` 覆盖 SEC-01~07 共七项，每项按「前置条件 / 操作 / 可观测结果 + 当前实际 + 当前判定」三段式记录。
- 本课只记录现象、不提前修复（密钥明文命中除外），至少保留 1 条红；判定如实，不预填全绿。
- 一键 `make check-security` 调用 `scripts/check_security.py` 覆盖 SEC-05/06；README 注明入口与 `reports/` 查看方式。

### 12.3 学会审核 AI 写的代码（阶段重点）

- 七类拆解核查清单落进 Harness 规则与 `AGENTS.md`；检查步骤明确要求按七类逐项核查 AI 生成的代码。
- 七维度 + 三分法（可用 / 待修改 / 风险无效）评审表归档 `docs/AI代码审核评审表.md`，每份 AI 初稿留一行评审结论。
- 批量扫描固定为检查步骤（而非临时人工动作），覆盖本次新增文件并输出可读结果到 `reports/`。
- 准入流程：AI 初稿 → 自审 → 交叉评审 → 合入 main；缺任一环节不得合入 main。

## 13. 待明确事项（Anything UNCLEAR）

1. `max_attempts` 的具体取值与退避基数、jitter 幅度由实现取一组可演示的常量并在 `reports/` 记录，课件未给定数值。
2. 幂等键版本位固定 `v1`；若后续批改逻辑升级需换键，应另开变更显式说明，不在本课静默改键。
3. git tag 的标签名按交付时约定，本变更不预设具体名称。
4. SEC-01~07 各项的具体检查对象以课程任务清单为准；本规约只约束记录格式、覆盖数量与「至少 1 条红」，不替课程定义每项内容。
