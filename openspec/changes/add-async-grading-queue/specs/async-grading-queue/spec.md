## ADDED Requirements

### Requirement: R81 提交接口只承诺接收

提交作答的接口 MUST 把「发起」与「完成」拆成两次交互，响应只承诺已接收，不承诺已完成。

#### Scenario: 返回 202 与任务标识且不含评分结果

- **WHEN** 已登录学生以合法 `assignment_ref` 与 `content` 调用 `POST /api/submissions`
- **THEN** 响应状态码为 202，响应体含 `task_id`、`status` 为 `pending`、`status_url` 与 `attempts`
- **AND** 响应体不得包含 `score`、`result`、`feedback` 或任何评分结果字段

#### Scenario: 请求内不执行批改

- **WHEN** 任意一次提交请求处理期间
- **THEN** 系统不得调用批改执行逻辑，批改只在 `task_worker` 独立进程内发生
- **AND** 提交响应时间不与批改执行耗时绑定

#### Scenario: 拒绝非法输入与身份字段

- **WHEN** 请求不是 JSON 对象、含 `class_id` / `user_id` / `role` / `uploaded_by` 身份字段、含合同外字段，或 `content` 为空 / 超过 5000 字
- **THEN** 返回 400 且不产生任何提交记录或任务记录

### Requirement: R82 事务性发件箱与幂等键

提交记录与任务记录 MUST 在同一个数据库事务里写入，幂等键必须由业务含义派生并落在唯一约束上。

#### Scenario: 写入与入队同事务

- **WHEN** 一次合法提交到达
- **THEN** `grade_submissions` 与 `grade_tasks` 两条写入在同一个 `BEGIN IMMEDIATE ... COMMIT` 内完成
- **AND** 事务回滚时两条记录都不存在，不出现「提交了但没有任务」的孤儿提交

#### Scenario: 重复提交返回同一任务标识

- **WHEN** 同一班级、同一用户、同一 `assignment_ref` 下重复提交内容完全相同的作答
- **THEN** 两次响应返回相同的 `task_id`
- **AND** `grade_submissions` 与 `grade_tasks` 各只有一条对应记录

#### Scenario: 幂等键可派生且带版本

- **WHEN** 系统为一次提交生成幂等键
- **THEN** 键形如 `grade:<submission_id>:v<version>`，由提交编号与版本派生，不使用随机值
- **AND** 内容变更或版本递增后生成不同的键，重新批改不被旧键挡住

### Requirement: R83 消费者独立启停与至少一次投递

消费者 MUST 是独立于 Web 服务的进程，可随时启停；崩溃或进程终止不得丢失任务。

#### Scenario: 停止消费者时提交仍成功

- **WHEN** 消费者进程未运行期间提交一份作答
- **THEN** 提交接口返回 202 与 `task_id`
- **AND** 任务状态停留 `pending` 且 `attempts` 为 0，重复查询状态不改变任何字段

#### Scenario: 恢复消费者后自动执行

- **WHEN** 启动消费者进程
- **THEN** 该任务被自动认领并经历 `pending → running → succeeded`
- **AND** 无需重新提交，`attempts` 为 1，结果可凭 `task_id` 查询

#### Scenario: 崩溃遗留任务被重投

- **WHEN** 消费者在任务处于 `running` 时终止后再次启动
- **THEN** `recover_stale()` 把该任务放回 `pending` 等待重投
- **AND** 重投不产生第二份结果（由 R85 保证）

#### Scenario: 竞争消费

- **WHEN** 两个消费者进程同时认领同一条待处理任务
- **THEN** `BEGIN IMMEDIATE` 保证只有其中一个认领成功，一条任务只被执行一次

### Requirement: R84 只读状态接口与状态机

状态接口 MUST 只读、可安全重复调用，且状态机覆盖完整生命周期。

#### Scenario: 连续查询不产生副作用

- **WHEN** 对同一 `task_id` 连续多次调用 `GET /api/tasks/<task_id>`
- **THEN** 每次返回 200 且 `attempts` 保持不变
- **AND** 不触发任何执行、不新增结果记录

#### Scenario: 跨班与不存在统一 404

- **WHEN** 用户查询不属于本班的 `task_id`，或查询不存在的 `task_id`
- **THEN** 两种情况都返回 404 且响应不可区分

#### Scenario: 状态取值与转换

- **WHEN** 任务被认领、执行成功、可重试失败、重试耗尽或不可重试失败
- **THEN** 状态依次取 `running`、`succeeded`、`failed`、`dead`，且 `pending`/`failed` 可被重新认领
- **AND** 每次认领 `attempts` 递增，`started_at` 与 `finished_at` 被记录

### Requirement: R85 写结果处去重与失败重试

去重 MUST 发生在写入结果的语句上并依赖数据库唯一约束；重试必须有分类、上限、退避与死信。

#### Scenario: 重复投递只产生一份结果

- **WHEN** 同一条任务被重复投递并再次执行
- **THEN** `grade_results` 中该 `idempotency_key` 只有一条记录
- **AND** 评分保持不变，`attempts` 递增，任务状态收敛为 `succeeded`

#### Scenario: 唯一约束而非先查一遍

- **WHEN** 两个执行体几乎同时为同一幂等键写结果
- **THEN** 由 `grade_results.idempotency_key UNIQUE` 判定冲突，`INSERT OR IGNORE` 吸收后写入者
- **AND** 系统不依赖「先查询是否存在再决定写入」的应用层判断

#### Scenario: 可重试失败退避后重投

- **WHEN** 执行因依赖暂时不可用（transient）失败且 `attempts` 未达 `max_attempts`
- **THEN** 任务置为 `failed` 并写入 `next_retry_at`，间隔按指数退避叠加随机抖动
- **AND** 到点后可被重新认领，`error_kind` 记为 `transient`

#### Scenario: 不可重试失败与次数上限转死信

- **WHEN** 执行因输入不成立（permanent）失败，或重试次数达到 `max_attempts`
- **THEN** 任务置为 `dead`、`next_retry_at` 清空且保留 `error` 与 `error_kind`
- **AND** 死信任务不再被认领，可被 `GET /api/tasks/observations` 计数

### Requirement: R86 三条判据可复现并纳入一键回归

三条判据 MUST 能在命令行复现，且转为可重复运行的用例。

#### Scenario: 判据一响应时间与执行时间解耦

- **WHEN** 连续提交 20 次并记录每次响应时间，取 P95 与任务记录算出的单次执行耗时对比
- **THEN** P95 显著小于单次执行耗时，且所有响应体不含评分结果

#### Scenario: 判据二与判据三纳入一键命令

- **WHEN** 执行 `make check`（Windows 为 `pwsh -File scripts/check-all.ps1`）
- **THEN** 自动跑完停消费者不丢任务与重复不产生重复结果两条判据
- **AND** 输出归档到 `reports/evidence/async-acceptance.json`，退出码反映是否全部通过
