# 安全自查记录 · CampusClaw · 第 8 课

- **环境**：按 `README.md` 从零启动；当前 HEAD `bcc8716`；验收实例 `http://127.0.0.1:<随机端口>`，使用隔离的 `CAMPUSCLAW_HOME`（临时目录，跑完清理，不触碰项目 `data/`）。本次交付文件为工作区新增，提交与 tag 待交付者确认后单独开出。
- **身份与数据**：班级 A、班级 B；`teacher_a`、`student_a1`、`student_b1`、`teacher_b`（预置账号全部可登录）；两班各一份示例讲义（正文分别含 `A_ONLY_SEED` / `B_ONLY_SEED`）。
- **复现入口**：`pwsh -File scripts/check-all.ps1`（或 `make check`）；七项记录由 `uv run python scripts/acceptance_security.py --out reports/evidence/security-precheck.json` 生成，命令与原始输出见 `reports/evidence/`。
- **分工约定**：权限类 SEC-01～SEC-04 与资产类 SEC-05～SEC-07 分开复核，结果合并进本文件；SEC-08 素材共同准备。**本课只记录现象，不提前修复**；密钥真实明文命中是唯一例外。
- **编号范围说明**：本报告的 SEC-05 指密钥明文扫描、SEC-06 指依赖漏洞基线、SEC-07 指 MCP 审计日志字段检查；此编号属于本课七项自查记录。OpenSpec 的安全预检规格采用其自身要求编号，两者不应仅凭 SEC 前缀视为同一条目。保留原始编号和历史结论。
- **凭据说明**：下列命令使用仓库公开的内置演示口令（仅本机演示）；Bearer 令牌均为运行时动态签发，不写死、不落盘。

## 受保护接口清单（不带令牌应得 401）

| 方法 | 路径 |
| --- | --- |
| GET | `/api/materials/` |
| GET | `/api/materials/{id}` |
| POST | `/api/search` |
| GET | `/api/prompt` |
| GET | `/api/skills` |
| GET | `/api/conversations` |
| POST | `/api/submissions` |
| GET | `/api/mcp/tool-calls` |
| GET | `/api/qa/questions` |

## 写入类接口清单（越权检测重点）

| 方法 | 路径 | 允许角色 |
| --- | --- | --- |
| PUT | `/api/prompt` | 仅教师 |
| POST / PUT / DELETE | `/api/skills`、`/api/skills/upload`、`/api/skills/{id}` | 仅教师 |
| POST / PUT / DELETE | `/api/mcp/servers`、`/api/mcp/servers/{id}` | 仅教师 |
| POST | `/api/materials/{id}/reindex` | 仅教师 |
| POST | `/api/submissions` | 学生可写，按 `class_id` 隔离 |
| POST | `/api/qa/questions/{id}/accept\|close\|reopen` | 仅教师 |

## 七项检测 · 三段式记录

### SEC-01 未登录访问受保护接口

- **前置条件**：服务已启动；不携带任何令牌；上表 9 个受保护接口已列清单。
- **操作**：对清单中每个接口各发一次请求，记录 HTTP 返回码（`scripts/acceptance_security.py` 的 SEC-01 段）。
- **可观测结果 / 期望**：每个接口都返回 401。
- **当前实际**：`GET /api/materials/ → 401`、`GET /api/materials/1 → 401`、`POST /api/search → 401`、`GET /api/prompt → 401`、`GET /api/skills → 401`、`GET /api/conversations → 401`、`POST /api/submissions → 401`、`GET /api/mcp/tool-calls → 401`、`GET /api/qa/questions → 401`。
- **当前判定**：**绿**。
- **权限类四件事**：用什么手段查＝逐个接口发匿名请求；查了什么＝未登录时的响应码；判据＝全部 401；结果＝9/9 为 401。

### SEC-02 跨班访问与跨班检索

- **前置条件**：`student_a1`（A 班）、`student_b1`（B 班）已登录；B 班讲义 `id=2`；关键词索引已就绪。
- **操作**：带 A1 令牌 `GET /api/materials/2`；分别带 A1 / B1 令牌 `POST /api/search` 检索本班与他班独有词。
- **可观测结果 / 期望**：跨班访问 404；跨班检索空结果（0 条）；本班检索有结果，以证明检索能力本身可用。
- **当前实际**：跨班访问 → **404**；A1 检索本班 `A_ONLY_SEED` → **1 条**；A1 检索 `B_ONLY_SEED` → **0 条**；B1 检索 `A_ONLY_SEED` → **0 条**。
- **当前判定**：**绿**。
- **权限类四件事**：用什么手段查＝接口用例（跨班资源 + 跨班检索词）；查了什么＝跨班讲义是否可读、跨班知识库是否泄漏；判据＝访问一律 404、检索 0 条；结果＝均符合，展开见 `reports/risk-authz.md`。

### SEC-03 学生修改技能与提示词

- **前置条件**：`student_a1` 已登录；A 班 `class_prompts` 与 2 条预置 `class_skills` 存在。
- **操作**：带 A1 令牌 `PUT /api/prompt`（正文写「改过的提示词」）与 `POST /api/skills`，随后回查数据库。
- **可观测结果 / 期望**：403，且数据不变。
- **当前实际**：`PUT /api/prompt → 403`；`POST /api/skills → 403`；`class_prompts(A)` 正文**未变**；`class_skills(A)` 仍 **2 条**（预置 2 条）。
- **当前判定**：**绿**。
- **权限类四件事**：用什么手段查＝学生令牌调配置写入接口 + 数据库前后比对；查了什么＝角色校验是否可绕过、配置是否被改；判据＝403 且零写入；结果＝符合。

### SEC-04 技能工具绕过鉴权

- **前置条件**：`student_a1` 已登录；A 班材料 `id=1`；`index_jobs` 基线 2 条。
- **操作**：带 A1 令牌**不走技能路由**，直接调用写入类接口 `POST /api/materials/1/reindex` 与 `POST /api/mcp/servers`，随后回查任务表。
- **可观测结果 / 期望**：被拒绝，库里无变化。
- **当前实际**：`reindex → 403`；`mcp/servers → 403`；`index_jobs` 条数 **2 → 2**。
- **当前判定**：**绿**。
- **权限类四件事**：用什么手段查＝绕过技能路由直调写入接口 + 数据库计数；查了什么＝是否存在未受保护的写入口子；判据＝403 且不新增任务；结果＝符合。
- **说明**：本项目没有 `/api/tasks/{id}/grade` 这类批改写入 HTTP 接口，批改结果只能由消费者进程写入；`reindex` 与 MCP 登记是最接近的写入类接口，故以此做等价检测。

### SEC-05 密钥明文泄漏扫描

- **前置条件**：本机已拉全量提交历史（10 个提交）；扫描提交历史、前端产物、运行日志三处。
- **操作**：`make check-security`（等价 `uv run python scripts/check_security.py --out reports/evidence/security-baseline.json`）。
- **可观测结果 / 期望**：真实密钥明文 0 命中。
- **当前实际**：扫描 **10** 个提交、**139** 个前端产物文件、**6** 个运行日志文件；真实密钥明文 **0 命中**；另有 **2 处公开演示/测试固定常量**已逐条登记（`docs/上手教程.md:537` 的 `campusclaw-mcp-demo-token`、`scripts/acceptance_compose.py:71` 的固定 `SECRET_KEY`），二者非第三方密钥、不随仓库外发，故不计入命中、也未触发轮换。真实模型密钥只存于本机 `.env`，已 gitignore 且从未进入提交历史。
- **当前判定**：**绿**。

### SEC-06 依赖漏洞基线

- **前置条件**：依赖按 `requirements.txt` / `uv.lock` 安装；本机已安装 9 项声明依赖（`gunicorn` 带 `sys_platform != 'win32'` 标记，Windows 未安装）。
- **操作**：`make check-security` 的依赖审计部分（检测到 `pip_audit` 时在线比对，否则走离线清单登记）。
- **可观测结果 / 期望**：高危清零，或书面登记处置方式。
- **当前实际**：**离线依赖清单基线（未完成在线漏洞库比对）**；高危/严重＝**未知（降级，未在线比对）**；处置方式已书面登记（见 `reports/security-baseline.md`）。本机未安装 `pip-audit` 且不联网，按任务清单「高危清零，**或**书面登记处置方式」的后一种处理，降级如实标注，不谎称高危清零。
- **当前判定**：**绿**（走「书面登记处置方式」分支，降级已如实标注）。

### SEC-07 审计日志可追溯

- **前置条件**：`teacher_a` 已登录；审计表 `mcp_tool_calls` 与查询接口 `/api/mcp/tool-calls` 存在。
- **操作**：`GET /api/mcp/tool-calls` 回查，并 `PRAGMA table_info(mcp_tool_calls)` 对照期望字段。
- **可观测结果 / 期望**：能查到操作人、技能标识、结果状态、耗时、用量。
- **当前实际**：接口返回 **200**（当前 0 条记录）；实际字段 `id, class_id, server_id, tool_ref, status, detail, user_id, conversation_id, created_at`；具备 **操作人、结果状态**；**缺失 技能标识、耗时、用量**。
- **当前判定**：**红**。

## 红条与日志缺口（单独记一行）

- **至少保留 1 条红**：SEC-07。本课不修复，留给后续课次「安全检查与审计」当堂从红改到绿，并归档修复前后输出与提交号。
- **字段缺口一行**：缺 `技能标识`、`耗时`、`用量`；准备加在采集层 `campusclaw/mcp_skill.py::_record`（记技能标识与起止时刻）、写入层 `campusclaw/mcp_db.py::record_tool_call`（增 `skill_ref` / `duration_ms` / `usage` 列）、查询层 `campusclaw/views/mcp_views.py` 的 `/api/mcp/tool-calls`（把新字段带出）。后续课次的监控指标（调用耗时、失败率、用量）以这些字段为数据源。

## SEC-08 素材（只准备，不试）

`reports/sec08-materials/` 下 1 份含「忽略以上指令」内容的讲义文档与 `questions.md` 中 3 条诱导提问（索要提示词原文、要求改变评分规则、要求绕过权限）。本课**不上传、不提问**，留给后续课次当堂试，避免破坏「先观察失败」的顺序。

## 汇总

| 判定 | 条数 | 编号 |
| --- | --- | --- |
| 绿 | 6 | SEC-01 ～ SEC-06 |
| 红 | 1 | SEC-07 |

原始输出：`reports/evidence/security-precheck.json`；独立复现输出：`reports/evidence/security-precheck-recheck.json`（7 条 / 6 绿 1 红，判定一致）。
