# CampusClaw｜班级答疑广场

CampusClaw 是面向课程班级的教学材料管理、知识检索与协作答疑系统。教师维护本班讲义和答疑知识，学生按班检索资料、查看来源并参与问答；AI 能力以检索证据为基础，未检索到依据时明确说明。

## 项目能力

- **教学材料与知识检索**：管理 Markdown / UTF-8 文本材料，按班隔离；提供关键词检索。向量与混合检索需要可选的 Qdrant 服务和已配置的嵌入模型；结果包含材料、切片和来源位置。
- **解题助手**：围绕本班材料开展会话，可选引导或直接回答；支持流式响应与来源引用。无模型配置时关键词检索仍可用。
- **班级答疑广场**：问题、回复、采纳、关闭及教师管理；教师确认后可将 FAQ 发布为本班知识材料。
- **异步批改**：提交接口返回任务标识，独立 SQLite 消费者处理队列；当前批改采用确定性本地规则，不是真实大模型评分；支持状态查询、重试与幂等结果。三项异步验收入口及历史证据见[异步批改说明](docs/IMPLEMENTATION.md#异步批改)和[验收记录](reports/demo-walkthrough.md)。这不代表项目 37 个业务验收场景已通过。
- **MCP 工具接入**：教师管理服务和工具白名单，工具调用按授权服务层执行并记录审计。

## 技术架构

Python 3.11、Flask 3.1、SQLite/FTS5、Jinja 服务端页面、JSON 与 SSE API。LangChain 提供模型适配，Qdrant 是可选向量检索后端；`uv.lock` 锁定本地依赖，Compose 定义容器服务。主要代码位于 `campusclaw/`，应用入口为 `app.py`，独立工具服务位于 `mcp-server/`。

## 快速启动

需要 Python 3.11 和 uv。在项目根目录运行：

```bash
uv sync --locked
uv run python app.py
```

打开 <http://127.0.0.1:8080/login>。本机首次启动会初始化 `data/` 与 `uploads/`。仅在本机演示时可使用文档所列预置账号；对外部署必须配置真实密钥和口令并启用严格配置。详细配置、Docker Compose 与 Windows 脚本见[实现说明](docs/IMPLEMENTATION.md)。

## 使用演示

登录后，教师可在 `/materials` 管理材料，在 `/knowledge` 试用检索，在 `/qa` 管理班级问题；学生可在 `/tutor` 使用解题助手并在 `/qa` 参与答疑。异步批改 API 为 `POST /api/submissions`，查询 `/api/tasks/{task_id}`；消费者可用 `uv run python -m campusclaw.task_worker` 启动。页面、接口与隔离验收命令详见[使用与实现说明](docs/IMPLEMENTATION.md)。

## 当前状态

当前 `main` 包含可运行的 Python/Flask 实现及异步批改模块。已归档的异步三项判据和安全自查证据只适用于各自记录的测试范围与批次；14 条业务需求、37 个验收场景仍须逐项按其状态执行，不能由局部验收推定全部通过。开发基线与差距见[当前实现基线](docs/implementation-baseline.md)。

## 验收与测试

六项门禁覆盖安全、异步、注入、审计、观测与容器配置，任一项判红即以非零退出码结束，同一份清单同时用于本地自检与 CI：

```bash
pwsh -File scripts/check-all.ps1   # Windows 入口
make check                         # 需 GNU make，等价
```

| # | 门禁 | 检查内容 |
| --- | --- | --- |
| 1 | `security` | SEC-05 密钥扫描 + SEC-06 依赖漏洞基线 |
| 2 | `async` | 第 8 课三条异步判据复现 |
| 3 | `apitest` | 第 9 课注入三件套反例（SQL / XSS / CSRF），20 条用例 |
| 4 | `audit` | SEC-07 审计日志七列结构断言与关联键断言 |
| 5 | `observe` | 第 10 课运行观测 5 条告警规则，`critical` 即红 |
| 6 | `compose` | 容器配置静态校验 11 项，不需要 Docker |

推送与 PR 由 [`.github/workflows/check.yml`](.github/workflows/check.yml) 执行同一份清单，证据以 `check-evidence` 产物归档；运行结果见 [Actions](https://github.com/Perry-xwr/campus-claw/actions) 与 [CI 运行记录](reports/evidence/ci-first-run.md)。

逐条判据、缺陷修复过程与红绿验证写在[验收与测试流程报告](reports/验收与测试流程报告-2026-11-12.md)。当前结论：**第 9 课 5 条判据全部通过；第 10 课 5 条通过、1 条（真实用户试用）未执行**——没有真实用户，不拿自测冒充。

门禁的价值不在「有一次通过」，而在**退出码随代码状态变化**：每一项都先构造坏提交确认退出码为 1，再修复确认回 0。只留一次绿说明不了任何问题，因为命令可能根本没在检查。仓库里两个已修缺陷都是这类情况——没有样本时直接把判定记为通过，以及 CI 上因缺数据库导致审计断言与观测规则一条都没执行、步骤却显示成功。

以上覆盖的是第 9–10 课的工程判据，**不等同于 14 条业务需求与 37 个验收场景全部通过**，后者逐项状态见[验收场景清单](docs/requirements/acceptance-scenarios.md)。

## 文档导航

- **运行与架构**：[实现说明](docs/IMPLEMENTATION.md)、[当前实现基线](docs/implementation-baseline.md)、[工程规范](docs/standards/backend.md)
- **产品与需求**：[项目需求](docs/requirements/project-requirements.md)、[功能规格](docs/requirements/functional-spec.md)、[角色与流程](docs/requirements/roles-and-workflows.md)、[14 项需求与 37 个场景](docs/requirements/acceptance-scenarios.md)、[集成要求](docs/requirements/integration-requirements.md)
- **质量与安全**：[测试规范](docs/standards/testing.md)、[安全规范](docs/standards/security.md)、[AI 规范](docs/standards/ai.md)、[产品规范](docs/standards/product.md)、[运维规范](docs/standards/operations.md)、[仓库协作规则](AGENTS.md)
- **验收与测试**：
  - 报告：[验收与测试流程报告（第 9–10 课）](reports/验收与测试流程报告-2026-11-12.md)、[验收测试报告（2026-11-10，基线 475eb45）](reports/verification/验收测试报告-2026-11-10.md)
  - 运行证据：[CI 运行记录](reports/evidence/ci-first-run.md)、[门禁红绿证据（含四项门禁时期原文）](reports/gate-red-green.md)、[容器实跑记录](reports/evidence/docker-acceptance.md)
  - 分项：[压测基线](reports/bench.md)、[审计日志回查](reports/audit-recheck.md)、[第 8 课异步演示记录](reports/demo-walkthrough.md)
- **安全与风险记录**：[安全自查](reports/security-precheck.md)、[安全修复记录](reports/security-fix-log.md)、[并发风险](reports/risk-concurrency.md)、[事务风险](reports/risk-transaction.md)、[权限风险](reports/risk-authz.md)
- **用户试用**：[试用模板](reports/user-trial-template.md)、[批次记录 2026-11-12](reports/user-trial-record.md)
- **历史设计**：[第 7 课团队交接](docs/lesson-07/team-handoff.md)、[历史骨架 OpenSpec](openspec/changes/2026-10-28-project-skeleton/proposal.md)（Go/React/MySQL 规划，不是当前架构或验收结果）

历史课程材料和原始报告用于追溯背景与证据，保留其原始范围和结论。
