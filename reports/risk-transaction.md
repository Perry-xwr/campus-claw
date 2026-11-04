# 高风险三查 · 事务 · CampusClaw

> 对应事务一条：写入提交记录与任务记录同事务；停消费者提交 → 恢复后恰好投递一次、无孤儿任务。来源：`reports/evidence/async-acceptance.json` 的 `判据二` 段。

- **用什么手段查**：事务性发件箱的写入边界 + 消费者停/启两次运行。先查 `task_db.submit()` 的事务范围，再在消费者不运行时提交一次作业、连续查询状态，随后启动消费者并轮询直到终态；同时在隔离库里核对 `grade_submissions` 与 `grade_tasks` 是否成对出现。
- **查了什么**：① 提交与任务记录是否在同一个原子操作内；② 消费者全部退出时提交是否仍成功；③ 恢复后是否**恰好投递一次**、是否有「提交了但没有任务」的孤儿提交；④ 状态接口是否只读（查询不推进执行）。
- **判据**：提交与任务同事务；停消费者时返回 202 且状态停留 `pending`、`attempts=0`；恢复后自动执行到 `succeeded`，`attempts=1`，**无需重新提交**；`grade_submissions` 与 `grade_tasks` 一一对应，无孤儿；连续查询状态不改变 `attempts`。
- **结果**：全部符合，**绿**。

## 当前实际（真实输出）

| 观测量 | 值 |
| --- | --- |
| 提交返回码 | **202** |
| `task_id` | `task_870a7f52bc3913ea` |
| 消费者停止期间连续 3 次查询 | 每次 `status=pending`、`attempts=0` |
| 状态序列（启动消费者后轮询） | `pending → running → succeeded` |
| 终态 `attempts` | **1**（恰好投递一次） |
| 结果是否可读 | 是（`result_present: true`） |
| 是否需要重新提交 | **否** |
| 消费者日志末行 | `task=task_870a7f52bc3913ea status=succeeded attempts=1 result_written=True` |
| 队列观测 | `pending=0`、`running=0`、`succeeded=22`、`dead=0` |

## 事务边界（代码级证据）

`campusclaw/task_db.py::submit()` 在**单个** `BEGIN IMMEDIATE ... COMMIT` 内完成两件事，任一步异常都由 `db.transaction()` 回滚：

```sql
BEGIN IMMEDIATE;
  INSERT OR IGNORE INTO grade_submissions
      (class_id,user_id,assignment_ref,content,content_hash,version,created_at) VALUES (...);
  SELECT id FROM grade_submissions WHERE class_id=? AND user_id=? AND assignment_ref=?
      AND content_hash=? AND version=?;
  INSERT OR IGNORE INTO grade_tasks
      (task_id,submission_id,class_id,user_id,idempotency_key,status,attempts,max_attempts,created_at,updated_at)
      VALUES (...,'pending',0,...,?,?);
COMMIT;
-- 响应此时才发出：202 + task_id，不含评分
```

选择事务性发件箱（先落待办、再由独立进程扫描投递）而不是「事务提交后再调代理投递」，是因为后者在事务成功而投递失败时任务会丢失，需要额外补偿；本实现保证「只要有提交，就一定有任务」。代价是入队有短暂延迟，且投递采用**至少一次**语义——重复投递由 `grade_results.idempotency_key UNIQUE` 吸收（见 `reports/risk-concurrency.md`）。

`campusclaw/task_worker.py` 启动时的 `recover_stale()` 把崩溃遗留的 `running` 放回 `pending`，实现崩溃恢复；`claim()` 用 `BEGIN IMMEDIATE` 认领，保证多个消费者下一条任务只被一个执行体取走。

## 复现命令

```powershell
# 方式一：自动跑完三条判据（含停/启消费者）
uv run python scripts/acceptance_async.py --out reports/evidence/async-acceptance.json

# 方式二：手工复现停/启（在项目根目录，隔离 CAMPUSCLAW_HOME 下）
# 1) 不启动任何消费者，登录并提交
curl -X POST http://127.0.0.1:8080/api/submissions `
     -H "Authorization: Bearer <token>" -H "Content-Type: application/json" `
     -d '{"assignment_ref":"hw8","content":"因为 A 所以 B。"}'
# 2) 反复查询，应始终 pending / attempts=0
curl http://127.0.0.1:8080/api/tasks/<task_id> -H "Authorization: Bearer <token>"
# 3) 启动消费者，任务被自动执行
uv run python -m campusclaw.task_worker --once
# 4) 再查，应为 succeeded / attempts=1，且带 result
```

## 与后续课次的关系

本文件是最终项目报告「高风险三查 · 事务」的直接素材；`started_at` / `finished_at` / `attempts` 与死信数量也是后续课次「失败率与延迟」监控指标的数据源。
