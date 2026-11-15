# 外部告警通知

## Why

现有运行观测已通过 `/api/health/alerts` 提供 `ok`、`degraded`、`critical` 判定，且 `scripts/check_observe.py` 可作轮询检查，但没有外部通知渠道。运维人员可能无法及时看到 critical 告警。

## What Changes

- 新增标准库实现的通知轮询器及 `scripts/alert_notify.sh` 入口。
- 通过环境变量配置只发往运维 webhook 的地址；凭据不进代码、日志或提交。
- 对 critical 规则集合去重，在 critical 清除时发送恢复通知。
- 为状态文件、超时、失败重试及 Windows/Linux 定时调用提供文档。
- 增加隔离 SQLite 与 Mock Webhook 回归测试。

## Non-goals

- 不修改现有告警阈值、状态判定、面板或健康接口契约。
- 不引入通知服务、消息队列或第三方 Python 依赖。
- 不在本变更中配置真实 Webhook 或启用操作系统定时任务。
