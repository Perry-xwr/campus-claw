# 实现基线审查记录与当前验证状态

## 历史审查记录（2026-11-04）

以下差距表依据提交 `e12d0e032bc843e395dcc942dbe77bfa94b2b150` 的静态代码/配置审阅；当时未安装依赖、运行服务或修改业务实现。表中“未验证”反映该次审查时的证据边界，不应覆盖其后的运行记录，也不自动代表问题已修复。

## 架构基线

Python 3.11、Flask 3.1，`app.py`导入`campusclaw.create_app`；业务蓝图和原生Jinja模板位于`campusclaw/views`、`templates`。SQLite是事实存储，`db.py`启用外键、5秒busy_timeout和`BEGIN IMMEDIATE`事务；初始化/增量建表散布在各模块。LangChain用于分块/生成，SQLite FTS5关键词检索，Qdrant可选向量检索；独立`mcp-server/`以FastMCP运行并要求Bearer。依赖主清单是pyproject+uv.lock；requirements.txt供Docker构建。Compose包含app、worker、qdrant、mcp；本地uv及PowerShell脚本也提供启动方式。

历史`openspec/changes/2026-10-28-project-skeleton`描述Go/React/MySQL、web/api/mysql和L7最小骨架，是早期规划，保持原样；不作为当前项目架构/代码实现规范，不能据其任务或Scenario宣称当前实现通过。strict和原课程验收仍为NOT_RUN。

## 旧要求→当前实现→处理

分类：A文档过时；B技术不同但可等价验证；C已发现缺口/需按业务需求修复；D尚未验证。

|旧规范要求|代码可见现状|分类与处理|
|---|---|---|
|Go cmd/internal/ports/adapter分层|Flask入口+views+业务/DB模块，没有强制该目录结构|A：backend改用现有结构；保持职责隔离，不重建框架。|
|React和状态页|服务端Jinja、内联CSS/JS、JSON及SSE|A：product按模板/渐进增强规范。|
|MySQL、SELECT1 ready探针|SQLite `/health`检查必需表，失败503；无独立ready|A：operations改按SQLite探针；C：若后续部署需要独立ready由需求变更确定，不谎称现有有ready。|
|独立Go/Node多阶段镜像、单命令check.py|Python 3.12 slim，pip安装requirements；Compose四服务；本机uv/Python脚本|A：改适配实际命令。C：容器用`:latest`，只用于开发现状；发版须锁定digest/不可变tag。|
|单行JSON及request ID日志|应用使用Python logging；未见统一JSON formatter及请求ID中间件|C：当前规范不得声明已满足，后续实现和日志脱敏验证。|
|测试隔离与全量一键门禁|README selfcheck仅临时目录启动、登录四账号、health/可见材料数；未见tests目录或37场景suite|C/D：不满足完整场景测试覆盖；需B新增pytest/Flask client隔离测试，逐SC追溯。selfcheck不得冒充全套。|
|SQLite事务/并发|db.transaction BEGIN IMMEDIATE，外键开启，busy_timeout 5000；worker在外部调用与分段事务间切换|B：用SQLite锁/提交故障测试。D：端到端worker并发与FAQ一致性尚未验证。|
|Cookie/Bearer安全|会话、bcrypt、CSRF；API Bearer；MCP独立Bearer；公开默认演示账号和默认密钥，strict可拒绝|B：严格模式、CSRF、令牌测试。C：README及启动横幅暴露公开演示口令，只能本机；公网须strict和替换全部凭据。|
|FAQ状态和撤销/索引补偿|FAQ生成真实Markdown聚合材料并入index_jobs；有revoke/republish及worker failed状态|B/D：注入索引失败、撤销、迟到worker任务并检查旧向量和聚合材料删除/重建；当前README建议重启补建不能代替故障测试。若撤销后旧向量仍可检索列C修复。|
|引用/Pprompt版本|检索结果含材料/chunk区间；AI/RAG代码可见。运行时Prompt追踪与每版本评测证据未确认|D：审计调用链和日志后验证；Prompt无可追溯版本或引用未回查列C修复。|
|14业务需求/37 Scenario|需求文件保留完整；selfcheck仅覆盖少量身份/材料路径|C：不得降级；逐需求编写测试并记实际状态。当前全体业务Scenario NOT_RUN。|

## 当前验证状态（2026-11-10）

本次更新前后已执行的局部验证包括：异步队列隔离验收脚本三项判据通过；临时数据目录下 `/health` 与 `/login` 返回 200；以 SQLite 只读连接确认 A 班 Docker、Python、RAG 材料存在且索引为 ready，`keyword_search` 对 Docker 返回相关切片及来源。Python 环境导入和上述验证均未调用外部模型 API。这些结果仅覆盖所列范围。

14 条业务需求及 37 个 `SC-*` 场景仍按 [验收场景](requirements/acceptance-scenarios.md) 各自标注；异步队列三项判据不等同于 37 场景验收。历史骨架 OpenSpec 的 strict 和骨架验收仍为 NOT_RUN。结构化日志、请求 ID、FAQ 撤销/迟到索引任务等差距应依据当前代码和新证据另行复核。
