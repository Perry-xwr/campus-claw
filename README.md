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
