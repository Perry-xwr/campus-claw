# 班级答疑广场

独立小组项目。仓库包含规范文档与一份可运行的个人实现（CampusClaw，作为答疑广场的业务底座），启动与使用说明见 [实现说明](docs/IMPLEMENTATION.md)。

本次第 7 课范围是 `2026-10-28-project-skeleton` 的最小骨架规划；OpenSpec strict 校验、软件实现和工程验收仍待执行，不应将**规范文档**视为已验收软件。

## 文档入口

- [项目功能说明](docs/requirements/project-requirements.md)
- [第 7 课团队交接](docs/lesson-07/team-handoff.md)
- [第 7 课验收清单](docs/lesson-07/acceptance-checklist.md)
- [骨架变更提案](openspec/changes/2026-10-28-project-skeleton/proposal.md)
- [骨架设计](openspec/changes/2026-10-28-project-skeleton/design.md)
- [骨架规格](openspec/changes/2026-10-28-project-skeleton/specs/skeleton/spec.md)
- [骨架任务](openspec/changes/2026-10-28-project-skeleton/tasks.md)

工程启动和测试命令见 [实现说明](docs/IMPLEMENTATION.md)（`uv sync` → `uv run python app.py`）。

## 当前 Python 实现与工程规范

仓库当前代码采用 Python/Flask/SQLite、原生模板、uv及Docker Compose，真实架构、启动方式和差距见[当前实现基线](docs/implementation-baseline.md)。工程规范按该实现维护；组员无须为早期骨架方案改写技术栈。`openspec/changes/2026-10-28-project-skeleton/`保留为历史Go/React/MySQL骨架规划，strict及原骨架验收仍为NOT_RUN，Python实现不构成其验收通过。

## 后续业务规范入口

未来五模块开发必须阅读[详细需求](docs/requirements/functional-spec.md)、[角色与流程](docs/requirements/roles-and-workflows.md)、[验收场景及追溯](docs/requirements/acceptance-scenarios.md)、[现有系统集成要求](docs/requirements/integration-requirements.md)。
组员优先复用自己的现有系统，具体技术栈/API/表结构由开发者确定并登记；后续集成方式以integration-requirements为准，早期独立部署建议不强制沿用。骨架OpenSpec仍仅适用于骨架，五模块通过后续独立功能变更实施。本轮文档补充不代表业务开发完成。组长旧个人项目不在修改范围。

---

## 第 8 课：异步任务、安全自查与代码审核

### 异步批改链路

`POST /api/submissions` 把「提交」与「批改」拆成两步，只承诺接收：

```bash
curl -X POST http://127.0.0.1:8080/api/submissions \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"assignment_ref":"hw8","content":"因为 A 所以 B，步骤完整。"}'
# → 202 Accepted
# {"task_id":"task_...","status":"pending","status_url":"/api/tasks/task_...","attempts":0}

curl http://127.0.0.1:8080/api/tasks/<task_id> -H "Authorization: Bearer <token>"
# → 200，状态 pending → running → succeeded，终态带 result
```

响应体**不含评分结果**；状态接口只读，重复查询不会触发执行或增加 `attempts`。批改在独立进程里跑，可随时启停：

```bash
uv run python -m campusclaw.task_worker            # 常驻消费者
uv run python -m campusclaw.task_worker --once     # 把当前队列跑完就退出
```

零模型环境也能完整演示：批改用确定性本地逻辑，执行耗时由 `CAMPUSCLAW_TASK_DELAY_MS` 控制（默认 0），重试上限由 `CAMPUSCLAW_TASK_MAX_ATTEMPTS` 控制（默认 3）。提交记录与任务记录写在同一个事务里（事务性发件箱），幂等键 `grade:<submission_id>:v1` 落在结果表唯一约束上，重复提交与重复投递都只产生一份结果。跨班查询与「不存在」统一返回 404。

**本次交付不改动既有索引链路**（`index_jobs` / `index_worker` / `POST /api/materials/{id}/reindex` 保持原样）；课件 queue.html 允许用数据库任务表 + 定时扫描达到三条判据，因此没有引入 Redis / RabbitMQ 等独立 broker。

### 一键检查

| 命令 | 作用 | 证据 |
| --- | --- | --- |
| `make check-security` | SEC-05 密钥明文扫描、SEC-06 依赖审计基线 | `reports/evidence/security-baseline.json` |
| `make check-async` | 第 8 课三条判据复现 | `reports/evidence/async-acceptance.json` |
| `make check` | 以上两项一起跑 | 同上 |
| `make check-apitest` | 既有接口回归套件 | `apitest/report.html`（本地产物） |

Windows 没有 GNU make 时用等价入口（自动探测项目 `.venv`）：

```powershell
pwsh -File scripts/check-all.ps1                 # 全部
pwsh -File scripts/check-all.ps1 -Mode security # 只跑安全基线
pwsh -File scripts/check-all.ps1 -Mode async    # 只跑三条判据
```

安全自查七项的真实执行另有一条命令：`uv run python scripts/acceptance_security.py --out reports/evidence/security-precheck.json`，在隔离的 `CAMPUSCLAW_HOME` 里起服务，不触碰项目 `data/`。

### 归档文件（仓库根目录 `reports/`）

| 文件 | 内容 |
| --- | --- |
| `security-precheck.md` | 七项检测的三段式记录、受保护接口清单、写入类接口清单 |
| `risk-authz.md` | 「高风险三查 · 权限」：SEC-02 跨班专项与可原样复跑的命令 |
| `risk-concurrency.md` | 「高风险三查 · 并发」：重复提交 / 重复投递只出一份结果 |
| `risk-transaction.md` | 「高风险三查 · 事务」：同事务写入、停消费者后恰好投递一次 |
| `security-baseline.md` | 密钥扫描与依赖审计的命令、输出原文与降级说明 |
| `review-01.md` | 交叉评审记录（用什么手段查 / 查了什么 / 判据 / 结果） |
| `sec08-materials/` | SEC-08 素材：含指令覆盖内容的讲义 + 3 条诱导提问（本课只备不试） |

### AI 代码审核与准入

- `AGENTS.md` 是 Harness 规则文件：七类拆解核查清单、四步拆解法、本仓库红线、沉淀反哺要求。
- `docs/AI代码审核评审表.md` 是本组评审表（七维度 + 三分法结论），随评审记录归档。
- 准入流程固定为 **AI 生成初稿（注明生成范围）→ 自己逐段审核 → 交叉评审（意见留痕）→ 测试通过、证据归档后合入 main**。机器能判的交给 `make check` / `make check-security`，人工重点复核权限、并发、事务、数据一致性。
- **未经审核的 AI 原生代码不得合入主干分支 `main`**；跳过审核按流程违规记录，与代码缺陷同等处理。

> 完整的项目使用说明（快速开始、配置、页面与接口、目录结构、自检）见本仓库 `docs/IMPLEMENTATION.md`；第 8 课的全部记录见 `reports/`。
