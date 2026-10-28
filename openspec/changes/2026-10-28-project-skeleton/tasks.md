# Tasks

仅本次骨架；所有框初始未勾选。前置：按docs/lesson-07/team-handoff.md先建仓并保护main、完成极简首次提交，再导入规约/规范；三人确认功能说明中的技术栈、RAG边界与探针决策；propose与实现前strict成功。这里验证组再次strict是最终复核。未来业务不在apply清单。

## 0 apply前置门禁

- [ ] 0.1 组长/B：确认规约与工具版本，实际执行支持的strict校验，保存退出码0及原输出后才允许 /opsx-apply；未运行或失败不得进入实现。规约：SK-10；Scenario：SC-SK-10-04。

## 1 骨架实现（前置：仓库及规范已准备）

- [ ] 1.1 A/B：按功能说明冻结版本创建分层和最小web页面，L审依赖方向。规约：SK-01；Scenario：SC-SK-01-01, SC-SK-01-02。

- [ ] 1.2 A：实现外置配置与监听前校验；提交安全.env.example/.dockerignore。规约：SK-02；Scenario：SC-SK-02-01, SC-SK-02-02, SC-SK-02-03。

- [ ] 1.3 A：实现MySQL真实探测和disabled RAG状态；health/ready。规约：SK-03；Scenario：SC-SK-03-01, SC-SK-03-02, SC-SK-03-03, SC-SK-03-04。

- [ ] 1.4 A：实现运维诊断与令牌验证，参数白名单。规约：SK-04；Scenario：SC-SK-04-01, SC-SK-04-02, SC-SK-04-03, SC-SK-04-04, SC-SK-04-05。

- [ ] 1.5 A：统一错误、404/405/recovery、request ID和JSON日志。规约：SK-05, SK-06；Scenario：SC-SK-05-01, SC-SK-05-02, SC-SK-05-03, SC-SK-06-01, SC-SK-06-02, SC-SK-06-03。

- [ ] 1.6 A/B：多阶段镜像、Compose和同源状态页，优雅退出。规约：SK-07；Scenario：SC-SK-07-01, SC-SK-07-02, SC-SK-07-03。

## 2 验证资产

- [ ] 2.1 B：按spec逐项实现所有自动场景和隔离fixture，A审断言；实现scripts/check.py。实现测试覆盖SK-01至SK-08的全部Scenario；门禁自身规约：SK-08；Scenario：SC-SK-08-01, SC-SK-08-02, SC-SK-08-03。

- [ ] 2.2 B：README落地实际命令/版本/故障操作；A按新环境逐行复核。规约：SK-09；Scenario：SC-SK-09-01, SC-SK-09-02。

- [ ] 2.3 L/B：检查AGENTS五类索引，记录新会话规范生效实验。规约：SK-10；Scenario：SC-SK-10-01, SC-SK-10-02。

## 3 验证、交叉评审与归档

- [ ] 3.1 L：运行实际版本支持的strict命令，修正文档直到退出0，保存原始输出。规约：SK-10；Scenario：SC-SK-10-04。

- [ ] 3.2 A/B：运行全部一键测试、Compose、缺配置/依赖故障、日志脱敏和Git全历史扫描；失败先修复。规约：SK-02, SK-03, SK-04, SK-05, SK-06, SK-07, SK-08；Scenario：SC-SK-02-01, SC-SK-02-02, SC-SK-02-03, SC-SK-03-01, SC-SK-03-02, SC-SK-03-03, SC-SK-03-04, SC-SK-04-01, SC-SK-04-02, SC-SK-04-03, SC-SK-04-04, SC-SK-04-05, SC-SK-05-01, SC-SK-05-02, SC-SK-05-03, SC-SK-06-01, SC-SK-06-02, SC-SK-06-03, SC-SK-07-01, SC-SK-07-02, SC-SK-07-03, SC-SK-08-01, SC-SK-08-02, SC-SK-08-03。

- [ ] 3.3 另一成员独立clone启动；三人分别留启动证据；交叉评审并关闭阻塞项。规约：SK-09, SK-10；Scenario：SC-SK-09-01, SC-SK-09-02, SC-SK-10-01, SC-SK-10-02。

- [ ] 3.4 L：所有门禁真实完成后执行课程archive步骤，核对归档spec和commit。规约：SK-10；Scenario：SC-SK-10-03。

- [ ] 3.5 L：按仓库流程合并归档并对已验收commit创建v0.0.1-skeleton，记录tag解析结果。规约：SK-10；Scenario：SC-SK-10-03。
