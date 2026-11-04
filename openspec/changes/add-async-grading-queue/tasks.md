# 第 8 课实施任务清单

按课件《实践步骤与验收》的五步顺序推进，顺序不可颠倒：先有能启动的队列与任务表，再改接口、再实现消费者。所有勾选均对应仓库中可找到的文件与可复现的命令。

## 1. 引入消息代理（编排与配置外置）

- [x] 1.1 判定实现形态：用 SQLite 任务表承担队列语义（课件 `queue.html` 明确允许「不用消息队列、用数据库任务表 + 定时扫描」达到三条判据），不引入 RabbitMQ / Redis / Celery，不引入新 Python 依赖。
- [x] 1.2 编排文件登记消费者独立启停入口：`Makefile` 的 `check-async` / `check-security` / `check`，Windows 等价入口 `scripts/check-all.ps1`。
- [x] 1.3 配置外置：执行耗时 `CAMPUSCLAW_TASK_DELAY_MS`、重试上限 `CAMPUSCLAW_TASK_MAX_ATTEMPTS` 一律从环境变量读取，不写死在业务代码里；数据库路径沿用 `CAMPUSCLAW_HOME`。
- [x] 1.4 应用初始化处接入：`campusclaw/__init__.py` 在 `prepare_storage_and_db` 调用 `task_db.ensure_schema(conn)`，在 `create_app` 注册 `task_views` 蓝图。

## 2. 建任务记录（含幂等键唯一约束，迁移可重复执行）

- [x] 2.1 `campusclaw/task_db.py` 新增 `grade_submissions` / `grade_tasks` / `grade_results` 三表，全部 `CREATE TABLE IF NOT EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS`，重复启动不报错、不改既有表任何一行。
- [x] 2.2 `grade_submissions` 落 `UNIQUE(class_id,user_id,assignment_ref,content_hash,version)`，挡住重复提交。
- [x] 2.3 `grade_tasks` 落 `task_id UNIQUE`、`idempotency_key UNIQUE`、`status CHECK IN ('pending','running','succeeded','failed','dead')`、`attempts`、`max_attempts`、`error`、`error_kind`、`next_retry_at`、`started_at`、`finished_at`。
- [x] 2.4 `grade_results` 落 `idempotency_key UNIQUE`，去重发生在写入结果的语句上，而非「先查一遍」。
- [x] 2.5 幂等键 `grade:<submission_id>:v<version>` 由业务含义派生，含版本与内容标识，不随机生成。

## 3. 改提交接口（写任务记录并返回 202 与任务标识）

- [x] 3.1 `POST /api/submissions` 用 `require_write_any`，拒绝身份字段与合同外字段，校验 `assignment_ref` 与 `content` 长度。
- [x] 3.2 事务性发件箱：`submit()` 在单个 `BEGIN IMMEDIATE ... COMMIT` 内写入提交记录与任务记录，不出现「只写了一半」。
- [x] 3.3 响应固定为 `202 Accepted` + `{task_id, status:"pending", status_url, attempts}`，**不含 score / result / feedback**。
- [x] 3.4 代码库中不存在「请求内调用模型并同步返回评分」的分支：批改只在 `task_worker` 进程里执行。
- [x] 3.5 班级隔离：任务按 `class_id` 归属，跨班与不存在统一 404。

## 4. 实现消费者（独立进程，可启停）

- [x] 4.1 `campusclaw/task_worker.py` 支持 `python -m campusclaw.task_worker` 常驻与 `--once` 单次两种模式。
- [x] 4.2 `claim()` 用 `BEGIN IMMEDIATE` 认领实现竞争消费；`recover_stale()` 在启动时把崩溃遗留的 `running` 放回 `pending`，实现至少一次投递。
- [x] 4.3 `complete()` 在单个事务里「写结果 + 标记 succeeded」，`INSERT OR IGNORE` 靠唯一约束吸收重复投递。
- [x] 4.4 零模型环境用确定性本地批改器；`CAMPUSCLAW_TASK_DELAY_MS` 提供可控执行耗时用于判据一。
- [x] 4.5 失败分类：`TaskInputError` 判 `permanent` 直接转 `dead`；其余按 `transient` 重试；指数退避 `1s/2s/4s…` 叠加最多 0.4s 抖动；达到 `max_attempts` 转 `dead` 并保留失败原因与 `error_kind`。

## 5. 补状态接口与重试（只读语义）

- [x] 5.1 `GET /api/tasks/<task_id>` 只读，不触发执行；连续查询 `attempts` 不变。
- [x] 5.2 `GET /api/tasks/observations` 提供队列长度、死信数、总重试次数、平均执行耗时。
- [x] 5.3 状态机覆盖 `pending → running → succeeded`，失败路径 `failed → running`（退避后）或 `dead`。

## 6. 三条判据复现与回归

- [x] 6.1 `scripts/acceptance_async.py` 在隔离 `CAMPUSCLAW_HOME` 下起真实 HTTP 服务，自动跑完三条判据，产出 `reports/evidence/async-acceptance.json`。
- [x] 6.2 判据一：连续提交 20 次记 P95，与任务记录 `started_at/finished_at` 算出的单次执行耗时对比；实测 P95 38.25ms、单次执行 266.05ms（7.0 倍）。
- [x] 6.3 判据二：停消费者提交 → 状态停留 pending 且 attempts=0 → 启动消费者 → `pending → running → succeeded`，attempts=1，无需重提交。
- [x] 6.4 判据三：同一提交连发两次得到同一 task_id；人为重复投递后结果表仍 1 行、score 74 不变、attempts=2。
- [x] 6.5 判据转为可重复运行的用例，接入 `make check`。

## 7. 安全自查与证据归档

- [x] 7.1 `scripts/acceptance_security.py` 真实执行 SEC-01～07，产出 `reports/evidence/security-precheck.json`；实测 6 绿 1 红。
- [x] 7.2 `scripts/check_security.py` 扫描全量提交历史、前端产物、运行日志；真实密钥明文 0 命中，2 处公开演示常量逐条登记。
- [x] 7.3 `Makefile` 提供 `make check-security`；README 注明入口。
- [x] 7.4 `reports/` 下固定产出六份记录：`security-precheck.md`、`risk-authz.md`、`risk-concurrency.md`、`risk-transaction.md`、`security-baseline.md`、`review-01.md`。
- [x] 7.5 并发与事务两条按「用什么手段查 / 查了什么 / 判据 / 结果」四件事写全；权限类 SEC-01～04 同样四件事写全。
- [x] 7.6 保留 SEC-07 一条红（审计日志缺技能标识 / 耗时 / 用量），后续课次从红改到绿；字段缺口与拟加在哪一层已单独记一行。
- [x] 7.7 SEC-08 素材只准备不试：`reports/sec08-materials/` 下 1 份含指令覆盖内容的讲义 + `questions.md` 三条诱导提问。
- [x] 7.8 知识库测试问题集草稿按有答案 / 无答案 / 跨班三类各写若干条。
- [x] 7.9 演示链路记录：登录取令牌 → 提交返回 202 与 task_id → 轮询 pending/running/succeeded。

## 8. AI 代码审核机制（阶段重点）

- [x] 8.1 七类拆解核查清单 + 四步拆解法 + 本仓库红线写进 `AGENTS.md`（Harness 规则文件）。
- [x] 8.2 七维度 + 三分法结论评审表归档 `docs/AI代码审核评审表.md`，含一份针对真实文件的已填写示例。
- [x] 8.3 批量扫描固定为检查步骤（`make check-security` / `make check`），高风险部分复核记录写清查了什么、依据哪条规约、结论。
- [x] 8.4 准入流程写进 `AGENTS.md`：AI 初稿 → 自审 → 交叉评审 → 合入 main；未经审核不得合入。

## 9. 版本与提交

- [ ] 9.1 本次自查单独开一条变更提交，提交信息写清依据的检查项（由交付者确认后执行）。
- [ ] 9.2 打与迭代说明同名的 git tag（如 `async-202`），用 `git tag -l` 输出为证（由交付者确认后执行）。
