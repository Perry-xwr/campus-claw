# CI 首次运行与 DEF-09：步骤显示绿，断言没跑

**记录时间**：2026-11-12 22:20–22:35
**仓库**：https://github.com/Perry-xwr/campus-claw
**运行页**：https://github.com/Perry-xwr/campus-claw/actions/runs/43236725387

## 一、首次推送即跑通

2026-11-12 22:23（UTC+8）推送 `c152577`，`check` 工作流第 1 次运行，**结论 success**，
耗时 31 秒（14:23:48 → 14:24:19 UTC）。

| # | 步骤 | 耗时 | 结论 |
| --- | --- | --- | --- |
| 1 | Set up job | 3s | success |
| 2 | 检出代码 | 4s | success |
| 3 | 安装 uv | 1s | success |
| 4 | 安装依赖（按锁文件，验证可复现） | 1s | success |
| 5 | SEC-05 密钥扫描 + SEC-06 依赖基线 | 1s | success |
| 6 | 第 8 课三条判据 | 11s | success |
| 7 | 第 9 课注入三件套 | 4s | success |
| 8 | SEC-07 审计七列结构断言 | <1s | success |
| 9 | 第 10 课运行观测告警判定 | 1s | success |
| 10 | 容器配置静态校验 | 2s | success |
| 11 | 归档证据 | 1s | success |

11 个实质步骤无一 `skipped`、无一 `cancelled`。证据产物 `check-evidence`
已上传，24,996 字节，未过期。

工作流本身也核对过：`.github/workflows/check.yml` 里六步都是真的
`uv run python ...`，没有 `|| true`、没有 `continue-on-error`、没有条件跳过。

## 二、疑点：三处 1 秒

「安装依赖」「SEC-05 依赖基线」「SEC-07 审计七列结构断言」都只用了 1 秒甚至
不到。全新 runner 上 `uv sync` 装 Flask + qdrant-client 只花 1 秒不合常理，
顺着查下去发现了实质问题。

## 三、DEF-09：CI 上两步是空转

**根因**：`.gitignore` 第 18、20 行排除了 `data/` 与 `*.db`，仓库里没有数据库。
干净 runner 检出代码后 `data/app.db` 不存在。

**两个脚本对「库不存在」的处理**：

| 脚本 | 库不存在时 | 后果 |
| --- | --- | --- |
| `scripts/audit_recheck.py --allow-empty` | `print("数据库不存在…跳过回查")` 后 `return 0` | `assert_schema()` 一条都没执行 |
| `scripts/check_observe.py` | `print("数据库不存在…跳过告警判定")` 后 `return 0` | `evaluate()` 未调用，5 条规则一条未计算 |

第 8 步的名字是「SEC-07 审计七列结构断言」，第 9 步是「第 10 课运行观测告警判定」。
**名字里写着断言和判定，实际什么都没断、什么都没判**，而两步都显示绿色。

`audit_recheck.py` 第 142 行的注释自己就写着「结构断言留给首次启动后的运行」——
即设计上知道这里不查，但 CI 从未有过「首次启动」。

## 四、红绿验证

在一个空目录里复现 CI 的状态：

```
$ python scripts/audit_recheck.py --db /tmp/ci_sim/app.db --allow-empty
数据库不存在（…\app.db），跳过回查：结构断言留给首次启动后的运行
EXIT=0                       ← 绿，但没有输出任何判定表

$ python scripts/init_schema.py --db /tmp/ci_sim/app.db
表数量：35
mcp_tool_calls 列（15）：id、class_id、server_id、tool_ref、status、detail、
                        user_id、conversation_id、created_at、action、
                        object_id、skill_id、duration_ms、tokens、request_id
必需表齐备
EXIT=0

$ python scripts/audit_recheck.py --db /tmp/ci_sim/app.db --allow-empty
| 列 | 含义 | 首条记录取值 | 判定 |
判定：绿
EXIT=0                       ← 绿，且这次真的列出了七列
```

观测那一步的差异更直接：

| 状态 | 输出 |
| --- | --- |
| 无库 | `数据库不存在（…），跳过告警判定` —— **0 条规则** |
| 建库后 | `规则数：5，未通过：0，跳过：1`，逐条列出 db_probe / index_failed / tasks_pending / http_p95_ms / audit_denials |

## 五、修复

新增 `scripts/init_schema.py`：按应用启动时的同一套 `db.apply_schema` +
各模块 `ensure_schema` 建出完整结构，**只建表不灌数据**，建完校验必需表齐备，
缺失即退出码 1。CI 在安装依赖后调用它。

为什么不是「给脚本加 `--allow-empty` 之外的新开关」：问题不在脚本判绿宽松，
而在于 CI 从来没有可查的对象。建不出库，任何开关都只是换个方式说「没查」。

## 六、副作用核查

- **apitest 不受影响**：`apitest/common.py` 的 `Server` 用独立
  `CAMPUSCLAW_HOME=apitest/appdata`，每次 `shutil.rmtree` 重建，不读 `data/app.db`。
- **init_schema 幂等**：本地已有 327,680 字节的 `data/app.db`，重复执行只做
  `CREATE TABLE IF NOT EXISTS` 与加列迁移，不动数据。

## 七、口径说明

- 首次运行（run #1）判据 3 成立——推送确实触发了构建，六步配置也确实都执行了。
- 但其中两步当时没有检查对象，**这条绿灯在 run #1 上的含金量要打折**。
- 修复后需再推一次，以 run #2 为准。数据侧的判定（有调用记录时的七列完整性、
  有请求时的延迟分布）CI 上仍无法覆盖——CI 没有运行时数据，这部分由本地实跑
  与报告正文的「判据 4/5 已实跑」承担。

## 八、附：后续运行

| 运行 | 提交 | 触发原因 | 结论 | 耗时 |
| --- | --- | --- | --- | --- |
| run #2 | `a0814ec` | DEF-09 修复 | success | 34s |
| run #3 | `7855f12` | 报告与证据文档更新（纯文档提交） | success | 37s |

run #3 的意义：它证明门禁的绿与 Markdown 文档改动无关，也说明 run #2 的绿
不是一次性的。三次运行全部 `success`，12 个步骤无一 `skipped`。

## 九、附：`init_schema` 幂等性实测

「只建表不灌数据」是设计意图，实测确认过。把本地 327,680 字节的 `data/app.db`
复制一份，在副本上执行 `init_schema`：

| 指标 | 源库 | 副本（执行前 → 执行后） |
| --- | --- | --- |
| 表数 | 35 | 35 → 35 |
| users | 4 | 4 → 4 |
| materials | 8 | 8 → 8 |
| knowledge_chunks | 5 | 5 → 5 |

数据一行未动。`apply_schema` 全部是 `CREATE TABLE IF NOT EXISTS`，各模块
`ensure_schema` 是加列迁移，重复执行不产生副作用。
