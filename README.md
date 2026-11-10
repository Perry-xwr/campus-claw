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

## 文档导航

- **运行与架构**：[实现说明](docs/IMPLEMENTATION.md)、[当前实现基线](docs/implementation-baseline.md)、[工程规范](docs/standards/backend.md)
- **产品与需求**：[项目需求](docs/requirements/project-requirements.md)、[功能规格](docs/requirements/functional-spec.md)、[角色与流程](docs/requirements/roles-and-workflows.md)、[14 项需求与 37 个场景](docs/requirements/acceptance-scenarios.md)、[集成要求](docs/requirements/integration-requirements.md)
- **质量与安全**：[测试规范](docs/standards/testing.md)、[安全规范](docs/standards/security.md)、[AI 规范](docs/standards/ai.md)、[产品规范](docs/standards/product.md)、[运维规范](docs/standards/operations.md)、[仓库协作规则](AGENTS.md)
- **验证记录**：[异步演示记录](reports/demo-walkthrough.md)、[安全自查](reports/security-precheck.md)、[并发风险记录](reports/risk-concurrency.md)、[事务风险记录](reports/risk-transaction.md)、[权限风险记录](reports/risk-authz.md)
- **历史设计**：[第 7 课团队交接](docs/lesson-07/team-handoff.md)、[历史骨架 OpenSpec](openspec/changes/2026-10-28-project-skeleton/proposal.md)（Go/React/MySQL 规划，不是当前架构或验收结果）

历史课程材料和原始报告用于追溯背景与证据，保留其原始范围和结论。
