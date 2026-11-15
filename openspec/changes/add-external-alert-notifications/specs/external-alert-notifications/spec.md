# 外部告警通知

## ADDED Requirements

### Requirement: 仅 critical 状态发送外部通知

系统 SHALL 通过配置的 Webhook 向运维端发送 critical 告警，消息包含告警类型、非敏感异常摘要和检测时间。通知不得包含凭据、用户内容、请求路径或动态原始告警文本。

#### Scenario: critical 告警出现

- **WHEN** `/api/health/alerts` 返回一个或多个未通过的 critical 规则
- **THEN** 通知器向配置的 Webhook 发送安全摘要和检测时间

#### Scenario: 状态正常或仅 warning

- **WHEN** 当前没有 critical 规则
- **THEN** 通知器不发送异常通知

### Requirement: 去重并通知恢复

系统 SHALL 持久记录成功发送的 critical 规则集合，避免同一集合重复通知；critical 告警清除后 SHALL 发送一次恢复通知。

#### Scenario: 重复告警

- **WHEN** 连续检查得到相同 critical 规则集合
- **THEN** 只发送首次告警

#### Scenario: critical 告警恢复

- **WHEN** 已通知的 critical 规则全部清除
- **THEN** 发送一次恢复通知并清除已通知状态

### Requirement: 外部调用失败可诊断且可重试

系统 SHALL 对网络错误、超时、非成功 HTTP 响应或无效接口响应设置有限等待、输出不含秘密的错误日志并返回非零状态。失败时 SHALL 不推进去重状态，以便下次运行重试。

#### Scenario: Webhook 不可达

- **WHEN** Webhook 超时或返回非 2xx
- **THEN** 记录安全的错误类别，退出非零且保留待通知状态
