# 高风险三查 · 并发 · CampusClaw

> 对应第 8 课判据三「重复不产生重复结果」。来源：`reports/evidence/async-acceptance.json` 的 `判据三` 段，由 `scripts/acceptance_async.py` 在隔离环境真实复现。

- **用什么手段查**：并发/重复两类来源各制造一次——① 同一份提交连发两次（重复提交）；② 任务完成后把 `grade_tasks.status` 手工放回 `pending` 再跑一次消费者，等价于代理未收到 ACK 后的**重复投递**；随后回查 `grade_results` 行数、`attempts` 与评分。
- **查了什么**：同一 `submission_id` 是否只产生一份生效结果；重复执行是否让评分变化；`attempts` 是否如实递增；状态接口是否只读。
- **判据**：结果表中该提交**只有一条**生效记录；`attempts` 递增而**评分不变**；重复提交两次得到**同一个 `task_id`**；去重由数据库唯一约束在「写入结果」那条语句上完成，而不是靠「先查一遍」。
- **结果**：全部符合，**绿**。

## 当前实际（真实输出）

| 观测量 | 值 |
| --- | --- |
| 第一次提交 `task_id` | `task_f31c9837a9eb89d9` |
| 第二次提交 `task_id` | `task_f31c9837a9eb89d9`（相同） |
| 重复投递后 `grade_results` 中该提交的行数 | **1** |
| 重复投递后 `attempts` | **2** |
| 重复投递前 / 后 score | **74 / 74** |
| 状态接口连续查询 `attempts` 是否变化 | 否（`status_api_readonly: true`） |
| 队列观测 | `succeeded=22`、`dead=0`、`failed=0`、`total_attempts=23`（22 个任务、1 次重投） |

## 去重为什么挡得住并发（四步拆解）

1. **它想保证什么**：同一份提交的同一版本，批改结果只能生效一次。
2. **它实际靠什么保证**：`grade_results.idempotency_key TEXT NOT NULL UNIQUE` + `INSERT OR IGNORE`；`grade_tasks.idempotency_key UNIQUE` 与 `grade_submissions` 的 `UNIQUE(class_id,user_id,assignment_ref,content_hash,version)` 挡住入口重复。
3. **什么情况下失效**：若改成「先 `SELECT` 查有没有，再决定 `INSERT`」，两个执行体同时查完都发现没有，就会各写一条；随机生成的幂等键也识别不出重复。
4. **挡得住的写法**：把规则交给数据库唯一约束，在执行体写结果的那一刻判定冲突；`task_db.complete()` 把「写结果 + 标记 succeeded」放在同一个事务里，重复执行只会被约束吸收，状态照样收敛。

幂等键 `grade:<submission_id>:v1` 由业务含义派生（含提交编号与版本），不是随机值；内容或版本变化会生成新键，正常重新批改不会被旧键挡住。

## 复现命令

```powershell
# 三条判据一起跑（隔离环境，不触碰项目 data/，约 10 秒）
uv run python scripts/acceptance_async.py --out reports/evidence/async-acceptance.json
# 或一键入口
pwsh -File scripts/check-all.ps1 -Mode async
```

重复投递那一步在脚本里是显式的一句 SQL，便于人工复核：

```sql
UPDATE grade_tasks SET status='pending', finished_at=NULL WHERE task_id='<task_id>';
-- 再执行：uv run python -m campusclaw.task_worker --once
```

## 失败分类与退避（同一脚本可复现）

`task_worker.grade()` 支持两个验收用故障注入开关：内容含 `PERMANENT_FAIL` 触发不可重试失败（直接转 `dead`），含 `TRANSIENT_FAIL` 触发可重试失败（按 1s / 2s / 4s 指数退避叠加最多 0.4s 抖动，达到 `CAMPUSCLAW_TASK_MAX_ATTEMPTS` 转 `dead` 并保留 `error` 与 `error_kind`）。死信数量由 `GET /api/tasks/observations` 计数，本次基线 `dead=0`。

## 与后续课次的关系

本文件是最终项目报告「高风险三查 · 并发」的直接素材；三条判据已转成 `make check` 中的用例，后续课次的自动化回归直接复用，不必重新设计。
