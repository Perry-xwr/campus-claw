# CampusClaw 仓库规则

本仓库当前实现是 Python 3.11 / Flask 3.1 / SQLite 的既有课程项目，包含原生 Jinja HTML、JSON/SSE API、LangChain、可选 Qdrant、uv 锁依赖及独立 FastMCP 服务。实现结构和启动方式以代码与[当前实现基线](docs/implementation-baseline.md)为准。

## 规则入口

- 当前实现差异和NOT_RUN证据：[当前实现基线](docs/implementation-baseline.md)。
- 产品与用户流程：docs/requirements/project-requirements.md、functional-spec.md、roles-and-workflows.md、acceptance-scenarios.md、integration-requirements.md。
- Flask/Python/SQLite：docs/standards/backend.md。
- Cookie/Bearer、CSRF、班级隔离与密钥：docs/standards/security.md。
- 页面与模板：docs/standards/product.md。
- LangChain、Qdrant、FAQ、MCP：docs/standards/ai.md。
- 验收：docs/standards/testing.md。
- uv、Compose、部署：docs/standards/operations.md。
- 执行变更前检查对应OpenSpec范围。`2026-10-28-project-skeleton`是历史独立Go/React/MySQL骨架方案，不适用于当前运行代码，也未因当前Python代码存在而视为完成或验收通过。新业务变更须独立定义并遵循本仓库现架构。

## 强制约束

1. 延续现有分层：`app.py`装配Flask，`campusclaw/views/`处理HTTP，业务服务与SQLite数据访问位于`campusclaw/`模块，模板位于`campusclaw/templates/`；按职责组织，不为满足历史目录名而重建。
2. 所有资源服务端按可信会话用户、角色和班级授权；跨班与不存在按需求统一404。Cookie写请求校验CSRF，Bearer只按既有API契约豁免。UI隐藏不构成授权。
3. SQLite使用参数绑定和明确事务边界；事务内不执行Qdrant、模型或MCP网络调用。写入需明确幂等和并发冲突语义。
4. AI证据须来自本次检索结果且班级/来源有效；无依据须拒答或明确降级；FAQ须教师确认后发布。工具调用沿现有受授权服务层。
5. 配置外置。开发演示默认值仅限本机；部署必须严格配置真实密钥/口令。日志不得泄露凭据或用户正文。
6. 只记录实际执行结果；未执行标NOT_RUN，发现实现缺口列待修复，不能改低需求或验收线。
7. Git提交、合并、推送、归档和标签按组长授权及仓库门禁执行。

Codex应先核对所在分支和`git status`，再编辑。任何适配文档若与代码不符，记录差异，不修改业务代码来迎合文档任务。

---

## 代码审查与准入规则

本次新增的完整 Harness 核查清单见 [AI 代码审核核查清单](docs/AI代码审核核查清单.md)：
七类拆解对象、四步拆解法、本仓库红线、三分法结论与准入四步。
评审表模板与已填写示例见 [AI 代码审核评审表](docs/AI代码审核评审表.md)；
安全自查三段式记录、并发/事务/权限三查与交叉评审记录见
[reports/security-precheck.md](reports/security-precheck.md)。

**未经审核的 AI 原生代码不得合入 `main`。** Git 提交、合并、推送、归档与标签
仍按本文件「强制约束」第 7 条的组长授权与仓库门禁执行。
