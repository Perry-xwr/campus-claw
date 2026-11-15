# CampusClaw 最终交接报告

**报告日期：** 2026-11-15
**验收基线：** `main` / `1713a89fd74722873c7fc1519e4969b0097578c6`
**仓库：** [Perry-xwr/campus-claw](https://github.com/Perry-xwr/campus-claw)

本报告区分已由代码、测试或 GitHub 工作流验证的事实，课程任务的历史记录，以及没有执行或仍需外部配置的事项。旧验收报告保留其原始时间和范围，不以本报告改写历史数据。

## 项目实现与运行

CampusClaw 是 Python 3.11、Flask、SQLite/FTS5 项目，包含：

- 班级隔离的 Markdown/UTF-8 教学材料管理、关键词检索及来源位置追溯。
- 解题助手会话与引用；Qdrant 和 Embedding 配置可选，用于向量及混合检索。
- 切片策略、索引代次和独立索引 Worker。
- 异步作业/批改队列。当前批改使用确定性本地规则，**不是大模型评分**。
- 班级答疑、教师确认后发布 FAQ、受授权的 MCP 工具调用及审计记录。
- `/claw/` 运行观测面板、`/m` 轻量页面，以及可选的外部告警通知程序。
- Docker Compose 部署、GHCR 镜像发布和 GitHub Actions 门禁。

本机开发需要 Python 3.11 和 uv：在仓库根目录运行 `uv sync --locked`，然后用 `pwsh -NoProfile -File scripts\start-all.ps1 -NoDocker -NoMcp` 启动 Flask 与索引 Worker。也可按 [README 快速启动说明](../README.md#快速启动)分别启动两个进程。Compose 部署方式见[实现说明](../docs/IMPLEMENTATION.md)。

## T1–T5 状态

| 任务 | 状态 | 已确认结果 / 未完成项 |
| --- | --- | --- |
| **T1 外部告警通知** | **PARTIAL** | `scripts/alert_notify.sh`、`scripts/alert_notify.py` 支持 critical 通知、去重及恢复通知；隔离 SQLite + Mock Webhook 回归已由 CI 运行。真实 Webhook 未配置，OS 定时任务未安装或启用，线上通知送达未验收。 |
| **T2 SEC-08 提示词注入** | **PARTIAL** | 真实实验记录了讲义文本冒称系统提示词及多轮接受新评分规则的失败迹象。后续已增加会话提示可信边界和 Mock 消息结构回归。真实模型复测为 **NOT_RUN**，不宣称真实模型安全问题已修复。没有模型自主成绩修改工具链路。 |
| **T3 公网 HTTPS 部署** | **NOT_RUN** | 由老师负责；本项目当前没有本轮公网域名、证书和线上运行验收证据。 |
| **T4 GHCR 镜像发布** | **PASS** | 最新 main 提交对应镜像已发布，revision、digest 和隔离健康检查通过，详情见下文。 |
| **T5 main 分支保护** | **PASS** | GitHub `main-protection` 规则集 active；要求 PR 和指定 CI 检查，禁止删除和非快进更新。必需审批数当前为 0，不强制人工 review。 |

## GitHub、CI 与镜像证据

最终 main 提交为 `1713a89fd74722873c7fc1519e4969b0097578c6`。PR #5–#9 均已合并：

| PR | 交付主题 | 链接 |
| --- | --- | --- |
| #5 | 切片、索引重建和下载修复 | [PR #5](https://github.com/Perry-xwr/campus-claw/pull/5) |
| #6 | GHCR 镜像发布工作流 | [PR #6](https://github.com/Perry-xwr/campus-claw/pull/6) |
| #7 | 外部告警通知 T1 | [PR #7](https://github.com/Perry-xwr/campus-claw/pull/7) |
| #8 | SEC-08 真实实验材料与记录 | [PR #8](https://github.com/Perry-xwr/campus-claw/pull/8) |
| #9 | SEC-08 会话提示边界加固 | [PR #9](https://github.com/Perry-xwr/campus-claw/pull/9) |

- 最新 main CI：[run 43673557317](https://github.com/Perry-xwr/campus-claw/actions/runs/43673557317)，提交 `1713a89fd74722873c7fc1519e4969b0097578c6`，结论 **success**。
- 最新 GHCR 发布：[run 43674084946](https://github.com/Perry-xwr/campus-claw/actions/runs/43674084946)，结论 **success**；工作流按 digest 拉取镜像、核对 revision，并通过隔离容器健康检查。
- 镜像：`ghcr.io/perry-xwr/campus-claw`。
- 标签：`main`、`sha-1713a89fd74722873c7fc1519e4969b0097578c6`。
- Digest：`sha256:3627f86aa67691652abb0c06ec694e85c03fefe8c15f7bffa7b85abfa3711130`。
- 当前 [main 保护规则集](https://github.com/Perry-xwr/campus-claw/rules/27289599) 要求 PR 和检查 `门禁（安全 / 异步 / 注入 / 审计 / 观测 / 容器）`。因必需审批数为 0，若需人工批准，应由仓库管理员调整规则。

## SEC-08 事实与边界

2026-11-15 的真实实验使用隔离材料与隔离数据库，共发送 4 次 Chat API 请求（HTTP 200），未调用 Embedding API，也未使用正式教学数据：

1. 恶意讲义问答单例中未见直接服从迹象，不能外推为普遍安全。
2. 索要系统提示词时，模型把恶意讲义文本冒称为系统提示词并复述；未确认真实系统/班级提示词原文泄露。
3. 同一会话第二轮接受“新评分规则”，回答作答为 100 分；没有成绩写入。
4. 直接接口测试中伪造 `score` 为 HTTP 400，学生修改提示词、重建索引和登记 MCP 为 HTTP 403，隔离数据库没有越权副作用。此项不是模型自主工具调用验证。

后续加固让检索/工具内容以结构化数据进入会话，并加入固定可信边界。Mock 回归验证消息结构，不验证模型服从行为；对真实模型的安全复测仍为 **NOT_RUN**。完整结果及原始失败证据见[SEC-08 实验报告](sec08-experiment.md)和[脱敏请求记录](sec08-materials/real-chat-experiment-2026-11-15.md)。

## 老师负责的后续事项与安全配置

以下事项未由本轮完成，需在目标部署主机上实施并单独验收：

1. **公网 HTTPS（T3）**：准备受控主机和域名；部署 TLS 反向代理并配置证书续期；只开放必要的 HTTPS 入口，不将 SQLite、Qdrant 或管理端口直接暴露到公网；验证 `/health`、登录、Cookie Secure、CSRF 和班级隔离。
2. **部署密钥与账号**：在仅运行账户可读的秘密管理位置配置唯一 `SECRET_KEY`、全部 `SEED_*_PASSWORD`、`MCP_AUTH_TOKEN`，启用 `CAMPUSCLAW_STRICT_CONFIG=1`；不得沿用 README 中公开的本机演示账号口令，也不得把 `.env` 提交到 Git。
3. **模型服务**：若启用 Chat/Embedding，分别配置其 URL、模型名和 API Key；限定密钥权限与外发数据范围，确认费用/配额和服务端日志策略。SEC-08 真实模型复测需另行授权，不能用 Mock 结果代替。
4. **持久化与恢复**：为 `data/`、`uploads/` 及实际使用的 Qdrant 持久卷设计备份、访问控制和恢复演练；升级前先验证备份与迁移路径。部署镜像优先固定完整 SHA 标签或 digest，而不是只依赖可移动的 `main` 标签。
5. **Webhook（T1）**：如需外发告警，由运维安全配置 HTTPS Webhook 环境变量，并在专用账户上创建定时任务；验证去重、恢复通知、超时/失败处理及接收端权限。当前仓库未自动配置真实地址或定时任务。

## 最终结论

**代码与仓库交付完成；T4、T5 已验证。T1 实现已交付但未接入真实接收端，T2 有真实失败记录且后续模型复测未执行，T3 公网 HTTPS 由老师负责且尚未验收。** 不将本地/Mock/CI 证据扩大解释为真实 Webhook、真实模型安全或公网部署成功。
