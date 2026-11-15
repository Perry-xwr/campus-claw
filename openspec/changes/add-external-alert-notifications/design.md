# 设计：外部告警通知

## 方案

`scripts/alert_notify.sh` 是 Linux/macOS 定时任务入口，调用 Python 标准库辅助实现；Windows Task Scheduler 直接调用同一 Python 文件。通知器通过现有匿名 `GET /api/health/alerts` 获取判定，不直接访问数据库，不修改观测规则。

仅使用 `CAMPUSCLAW_ALERT_WEBHOOK_URL`、可选 `CAMPUSCLAW_ALERTS_URL`、`CAMPUSCLAW_ALERT_STATE_FILE` 和 `CAMPUSCLAW_ALERT_TIMEOUT_SECONDS` 配置。Webhook 只接收事件类型、检测时间和由规则 ID 映射出的固定摘要，不转发动态 `title`、`hint`、阈值值或用户数据。

状态文件只保存已成功通知的 critical 规则 ID 集合。相同集合不重复通知；集合变化发送新的 critical 通知；已存在 critical 集合变为空时发送一次恢复通知。HTTP/网络失败不推进状态，下一次定时运行可重试。写状态采用同目录临时文件加原子替换；跨平台文件锁避免并行轮询重复发送。

## 安全和失败语义

- URL 仅从进程环境读取，从不打印或写入状态文件。
- HTTP 调用设置有限超时；日志只记录错误类别/HTTP 状态码，不记录异常对象、URL、响应体或 webhook 回执。
- 配置、响应、状态文件损坏、HTTP 错误和并发锁冲突均以非零退出码明确报告。
- 发送成功后再持久化状态；若进程在远端接受通知后、本地落状态前崩溃，可能出现一次重复投递，采用可恢复的至少一次语义。

## 验收

隔离临时 SQLite 通过现有 Flask 健康告警接口提供状态；本地 Mock Webhook 记录请求。覆盖正常无通知、critical 通知、重复去重、恢复通知、网络/HTTP 失败及失败后可重试。现有告警阈值和 CI 判据保持不变。
