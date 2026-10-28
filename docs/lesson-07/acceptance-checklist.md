# 第7课验收清单

日期：2026-10-28。依据：用户要求及已完整阅读的附件lesson7-requirements.md；原课件网页本次未能读取，未宣称重新核验原文。顺序为建仓库→定规约→立规范→落骨架。

**阶段性文件已生成；以下工程/平台/人工验收全部尚未执行。** 文件存在不等同strict通过或软件完成。TODO表示待实施，NOT_RUN表示待验证，不预填PASS。

|编号|项目与通过判据|责任人|当前状态|应保存的证据|
|---|---|---|---|---|
|CHK-01|独立小组仓库，教师和三人具有所需访问权限；main先保护|组长|TODO|仓库地址、成员和规则截图，脱敏|
|CHK-02|首个提交仅README.md、.gitignore、可选LICENSE；不得整包首提|组长/A|NOT_RUN|根提交文件清单及保护设置时间|
|CHK-03|README定位、工具版本、clone到运行可复现；.gitignore排除.env；后续.env.example仅空值/占位|A|TODO|README及ignore检查；不得上传.env|
|CHK-04|变更名正确，proposal/design/spec/tasks四份完整且只含骨架|组长|文档已生成，评审TODO|四文件、评审意见|
|CHK-05|实际OpenSpec版本支持的strict校验退出0|组长/B|NOT_RUN|版本、help、实际命令、退出码、原输出|
|CHK-06|AGENTS连接产品/后端/安全/测试/运维五类规范；新会话可读取并约束改动|组长/B|文件已生成，生效验证NOT_RUN|仅给路径与change名的新会话记录、五类违规识别结果|
|CHK-07|分层最小前后端运行，不含五模块业务实现|A|TODO|目录/import检查、状态页、构建输出|
|CHK-08|必需配置缺失或非法5秒内非零退出且不监听|A/B|NOT_RUN|逐项配置故障测试，不包含秘密值|
|CHK-09|免认证health含version/time/dependencies；MySQL断连health200、ready503|A/B|NOT_RUN|正常/断连/恢复HTTP与数据断言|
|CHK-10|参数非法400、无运维权限401、未知资源404、依赖不可达503|B|NOT_RUN|SC-SK-04-03/02、SC-SK-05-01、SC-SK-03-02测试|
|CHK-11|单行JSON日志，request ID贯穿header/body/log，无秘密|A/B|NOT_RUN|脱敏日志样本、JSON解析/关联测试|
|CHK-12|Dockerfile/Compose一命令启动，不依赖旧项目，120秒内ready成功|A/B|NOT_RUN|版本清单、构建输出、探针结果|
|CHK-13|一键自动化测试非零失败、隔离测试数据、Scenario追溯完整|B|TODO|scripts/check.py、summary.json、junit.xml|
|CHK-14|全部Git历史无真实明文密钥；若曾泄露先轮换再治理|B|NOT_RUN|扫描器版本、范围、脱敏报告和退出码|
|CHK-15|每人按README独立启动，另一成员独立clone及交叉评审|三人，B汇总|NOT_RUN|各机器OS/版本/commit/命令结果，A/B互审|
|CHK-16|docs/lesson-07中保存实际验收记录，失败有问题和复测记录|B|TODO|verification-record.md及脱敏证据路径|
|CHK-17|全部验收完成后运行archive，归档规约与实现一致|组长|TODO|实际工作流入口、输出、归档路径|
|CHK-18|v0.0.1-skeleton指向已验收commit，可解析且团队可访问|组长|TODO|tag目标及发布记录|

## 执行记录格式

B实施时创建 `docs/lesson-07/verification-record.md`，每条记录填写：CHK/SC/T编号、commit、执行人、时间、OS和工具版本、前置条件、实际命令、实际退出码、预期、实际结果、脱敏证据路径、状态、问题单及复测结论。人工步骤没有退出码时填写N/A及原因。失败不得勾选完成；工具缺失写BLOCKED/NOT_RUN。

本轮实际检查：本机 `Get-Command openspec` 未发现CLI，因此未运行strict；也未运行工程测试、Compose、GitHub配置、新会话复现、归档或tag。课程四步工作流如何映射本机入口见team-handoff。仅有文档静态检查不能替代上述任何验收。

2026-10-28文档静态检查实测记录：使用本机Python读取13份P0文件，检查非空、Markdown本地链接、10条Requirement包含SHALL和Scenario、32个Scenario编号唯一且都有GIVEN/WHEN/THEN、tasks引用覆盖全部Scenario且无未知编号、所有任务未勾选。脚本退出码0，发现0项结构错误。这只证明上述结构检查结果；不证明OpenSpec版本兼容、业务实现、运行环境或人工评审通过。
