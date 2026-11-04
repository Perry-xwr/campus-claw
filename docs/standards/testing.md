# 测试规范（pytest/Flask/SQLite）

本规范不声称仓库有完整pytest套件。README当前列出的入口为`uv run python scripts/selfcheck.py`，它启动临时应用、验证health、四账号登录跳转及材料可见数量/班级隔离；不覆盖全部业务需求。自检当前尚未执行，本规范适配任务不运行项目。

|规则|约束|检查方式|失败判定|
|---|---|---|---|
|TST-01 追溯|保留`docs/requirements/acceptance-scenarios.md`内14需求、37场景；每个场景映射测试标识T-<Scenario>。未实现/未执行分别记TODO/NOT_RUN。|B建立追溯表并对照全部FR、SC编号和测试文件/方法。|需求无测试映射、删场景或将未运行填PASS即失败。|
|TST-02 层次|优先pytest及Flask test_client；路由测HTTP/会话/CSRF/副作用，模块测业务/SQLite事务，少量端到端验证模板主流程。真实外部服务用stub；至少保留真实契约检查。|pytest若有则记录精确命令；现有自检用`uv run python scripts/selfcheck.py`。|只验证路由存在/HTTP200而不验证数据、权限和引用即失败。|
|TST-03 数据隔离|每测试使用tmp_path独立SQLite、隔离上传目录和测试配置；不触碰data/app.db、uploads或真实Qdrant。固定时钟、清理服务和临时进程。|断言临时路径；连续/乱序执行；检查失败清理。|测试依赖共享个人数据或清理项目数据即失败。|
|TST-04 一键入口|已存在的基线命令为`uv run python scripts/selfcheck.py`；它不是37场景全量测试，也无已证实JUnit报告。未来新增测试命令时更新README，并令失败非零退出。|实际运行前确认授权；当前仅审阅脚本内容。|把selfcheck说成全量验收、引用不存在`scripts/check.py`或虚构报告即失败。|
|TST-05 分域验收|Cookie登录+CSRF、Bearer写请求豁免、角色与班隔离需分别测试；AI真引用/无据拒答/MCP工具安全；FAQ索引失败/撤销迟到任务；SSE中断；SQLite锁/提交回滚；health依赖故障。|按37个SC逐条执行，保留环境、命令、状态码、DB/文件副作用和脱敏日志。|关键异常缺失、跨班数据暴露、撤销后重新出现即失败。|

建议测试放`tests/`并用pytest，但当前仓库文件清单中未见测试目录；不得声称已建立或运行。OpenSpec骨架Scenario与后续14条业务需求/37个Scenario分开追溯。
