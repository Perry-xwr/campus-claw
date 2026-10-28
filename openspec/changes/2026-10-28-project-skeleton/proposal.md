# Proposal

## Why
班级答疑广场尚无独立团队工程底座。先用一个可运行、可观测、可复现的骨架验证协作流程和规范入口，降低后续五模块实现时环境和授权边界不清的风险。

## What Changes
新增单向分层、配置验证、MySQL连通探测、公开health/ready、受令牌保护的运维诊断、错误外壳、request ID/JSON日志、最小web状态页、Docker/Compose和一键验收。严格限定 SK-01…SK-10。

## Capabilities
### New Capabilities
- skeleton：最小运行和工程门禁，见specs/skeleton/spec.md。
### Modified Capabilities
无。独立新项目，不假定旧CampusClaw服务已部署或具有兼容契约。

## Impact
影响未来backend/web/deploy/tests/scripts和规范入口。关系库只用于连通，不建业务表；RAG默认disabled。参考docs/requirements描述长期目标，但不自动扩大本change。

## Non-goals and Alternatives
不实现登录、发问、回复、AI问答、教师状态机、FAQ或统计业务。放弃直接复制旧CampusClaw整库/整套服务：会隐含旧凭据、旧部署与过大范围。选择接口设计经验复用与未来适配器接入，代价是需另做契约测试。

## Approval
功能说明中的技术栈、RAG边界与探针决策及工具版本需三人冻结；当前状态REVIEW_REQUIRED。文件生成不表示 /opsx-propose 或 strict 已执行。
