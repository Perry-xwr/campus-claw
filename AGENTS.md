# 班级答疑广场：仓库规则

按组长授权及当前OpenSpec变更范围开发；`2026-10-28-project-skeleton` 只允许最小骨架，不实现五模块业务。

## 必须读取的入口

- 产品范围：[功能说明](docs/requirements/project-requirements.md)。实现以对应change的proposal/design/spec/tasks为准；冲突先修订文档并记录原因。
- 前端、页面与交互：读取 [product](docs/standards/product.md)。
- `cmd/`、`internal/`、API与配置：读取 [backend](docs/standards/backend.md)。
- 所有路径：读取 [security](docs/standards/security.md)；密钥不入代码、日志、镜像或Git。
- 测试、脚本及任何行为变更：读取 [testing](docs/standards/testing.md)。
- Docker、Compose、部署、README：读取 [operations](docs/standards/operations.md)。
- 验收和分工：读取 [team-handoff](docs/lesson-07/team-handoff.md) 和 [acceptance-checklist](docs/lesson-07/acceptance-checklist.md)。

## 强制约束

1. handler→application→domain/ports；adapter实现port，cmd装配。SQL只在数据适配层，数据库事务内不得调用外部网络。
2. 对每项资源按可信身份和class_id授权；跨班与不存在404；未知筛选400。不得依赖UI隐藏按钮判权。
3. 写入必须明确幂等/版本冲突行为；不得静默覆盖并发修改。AI引用必须可验证，未经教师确认不得发布可信FAQ。
4. 配置外置、缺失先退出；health免认证且无敏感详情；请求带request ID，日志单行JSON。
5. 只以实际命令输出记录验证结果；未运行写NOT_RUN，失败不删断言、不放宽门禁。所有任务勾选需有证据。
6. Git提交、合并、push、归档及tag须按组长授权和验收门禁执行，不得未经授权操作。

上面的路径作用域是要求代理主动读取的规则索引，不是虚构的glob自动加载功能。新会话需在本目录/未来仓库根启动，核对是否有上层或同层AGENTS.override.md覆盖，并做真实规则生效实验。

- AI/RAG、Prompt及FAQ相关变更：读取 [AI应用规范](docs/standards/ai.md)；仅在未来对应变更生效，不扩大当前骨架任务。
