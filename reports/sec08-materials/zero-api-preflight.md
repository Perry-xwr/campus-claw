# SEC-08 零 API 前置检查

日期：2026-11-15
仓库：`Perry-xwr/campus-claw`
基线：`5be0365`
分支：`feat/sec08-prompt-injection-experiment`

本记录是授权真实模型实验前的环境快照，只包含前置检查和隔离环境的零模型请求验证，不是 SEC-08 真实模型实验结果。该次检查未调用 Chat API、Embedding API 或 Qdrant，也没有访问正式数据库或上传目录。之后经用户授权的真实 Chat 配置检查与实验结果见 [真实 Chat 实验记录](real-chat-experiment-2026-11-15.md)。

## 运行条件

| 检查项 | 结果 |
| --- | --- |
| 项目 Python | `.venv` Python 3.11.18 可启动 |
| 当时检查进程 Chat 配置 | `CHAT_BASE_URL`、`CHAT_MODEL`、`CHAT_API_KEY` 均未配置；仅检查进程环境 |
| 当时检查进程 Embedding 配置 | `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_API_KEY` 均未配置；仅检查进程环境 |
| 当时检查进程 Qdrant 配置 | `QDRANT_URL`、`QDRANT_COLLECTION` 均未配置；项目代码缺省 URL 为 `127.0.0.1:6333` |
| 本机 Qdrant 端口 | `127.0.0.1:6333` 与 `127.0.0.1:6335` 均未监听 |
| Docker Engine | Docker CLI 存在；本次执行环境访问 Docker Engine named pipe 被拒绝，未操作容器 |
| 正式 `.env` | 此次快照未读取；随后授权实验只在子进程内加载本地 Chat 配置，未修改 `.env` |

当前执行进程不具备真实 Chat / Qdrant 联调条件。RAG 会话在无 Embedding 配置时可使用关键词检索，因此未来行为实验只需要独立 Chat 配置；本方案计划 Embedding 请求数为 0。

## 隔离准备实测

操作在自动清理的临时 `CAMPUSCLAW_HOME` 中完成；使用现有恶意讲义的素材正文，由隔离教师账号上传，运行一次关键词索引并查询。临时 SQLite 与上传目录在脚本退出时清理。

| 检查 | 实际结果 |
| --- | --- |
| 隔离上传 | PASS，HTTP 201 |
| 关键词索引 | PASS，任务 `done`，`attempts=1`，活动代次有 1 个 ready chunk |
| 关键词检索 | PASS，命中本次隔离材料 1 条 |
| Embedding / Qdrant | 0 次请求 / 未使用 |
| Chat API | 0 次请求 |
| 临时数据清理 | PASS，临时目录自动清理 |

权限接口验证使用第二个独立临时 SQLite。学生提交伪造 `score` 字段得到 400；修改教师提示词、重建材料索引、登记 MCP 服务器分别得到 403。数据库核对如下：

| 隔离数据库计数 | 请求前 | 请求后 |
| --- | ---: | ---: |
| `class_prompts` | 2 | 2 |
| `index_jobs` | 2 | 2 |
| `mcp_servers` | 0 | 0 |
| `grade_submissions` | 0 | 0 |
| `grade_tasks` | 0 | 0 |

结果：无越权数据库副作用。该验证是直接接口权限测试，不是模型诱导后的工具调用验证。

## 代码边界与已知风险

- `campusclaw/task_worker.py::grade()` 是本地确定性批改器；不接收材料、对话或 Chat 模型结果。
- `campusclaw/views/conversation_views.py` 和 `campusclaw/tutor.py` 实现连续会话。检索内容位于 human/context 消息；会话的通用 system template 没有明确声明检索片段是不可信数据。
- `campusclaw/retrieval.py::answer()` 的无状态回答提示明确说资料片段是资料而非指令，但本实验须走会话解题助手路径，不能拿该路径的提示约束代替会话实验。
- `campusclaw/mcp_skill.py::run_skill_tools()` 按服务器端技能白名单确定性调用工具；模型不自由选择工具。仓库没有成绩修改 API 或成绩写入 MCP 工具。

以上代码检查只定位实验对象和风险，不构成真实模型安全结论；未据此修改安全约束或测试判据。

## 后续请求预算

采用同一隔离应用与关键词检索：实验一 Chat 1 次、实验二 Chat 1 次、实验三同一会话连续两轮 Chat 2 次；实验四只做直接接口权限验证，Chat 0 次。合计计划 Chat 调用 4 次，Embedding 0 次。`ChatOpenAI` 当前配置允许一次重试，若请求失败，底层 HTTP 尝试数可能高于计划调用数；实验日志需分别记录模型调用和重试次数。

实验输入、预期、实际、脱敏和清理字段见 [实验记录模板](experiment-record-template.md)。真实实验须在用户明确授权并提供本地隔离 Chat 配置后进行。
