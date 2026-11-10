# 演示链路 · 登录 → 202 → 轮询状态（第 8 课）

> **数据差异说明：**本文正文记录的演示数据为 P95 38.25 ms、单次执行 266.05 ms；归档 `reports/evidence/async-acceptance.json` 记录的生成时间为 2026-11-04T10:39:20Z，P95 35.03 ms、单次执行 265.25 ms。两处数据存在差异，正文数据与归档 JSON 的批次对应关系尚未确认。原始数值和证据均保留，不据此推断差异原因。

> 最终验收当堂演示原样使用这条链路。命令中的口令是仓库公开的内置演示值；
> Bearer 令牌运行时动态签发，不写死。Windows 用 PowerShell 7。

## 准备

```powershell
# 终端 1：按 README 从零启动（本机模式，零模型也能跑）
uv run python app.py

# 终端 2：先不启动消费者——判据二需要「消费者停止」这个状态
# 留空即可；准备好后再执行：uv run python -m campusclaw.task_worker
```

## 链路四步

```powershell
$base = "http://127.0.0.1:8080"

# ① 登录取令牌
$login = Invoke-RestMethod -Uri "$base/api/login" -Method Post `
  -ContentType "application/json" `
  -Body '{"username":"student_a1","password":"StudentA1#2026"}'
$token = $login.token
$h = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }

# ② 提交作业：返回 202 与任务标识，响应体不含分数
$job = Invoke-RestMethod -Uri "$base/api/submissions" -Method Post -Headers $h `
  -Body '{"assignment_ref":"hw8","content":"因为 A 所以 B，步骤完整。"}'
$job | ConvertTo-Json

# ③ 轮询状态：消费者未启动时稳定停在 pending
Invoke-RestMethod -Uri ($base + $job.status_url) -Headers $h | ConvertTo-Json -Depth 5

# ④ 启动消费者后再轮询：pending → running → succeeded
uv run python -m campusclaw.task_worker --once
Invoke-RestMethod -Uri ($base + $job.status_url) -Headers $h | ConvertTo-Json -Depth 5
```

## 真实输出（隔离环境自动复现，`reports/evidence/async-acceptance.json`）

**② 提交**：HTTP `202`，响应体

```json
{
  "task_id": "task_870a7f52bc3913ea",
  "status": "pending",
  "attempts": 0,
  "status_url": "/api/tasks/task_870a7f52bc3913ea"
}
```

响应中**没有** `score` / `result` / `feedback` 字段；20 次提交的 P95 为 **38.25 ms**，而任务记录算出的单次批改执行耗时为 **266.05 ms**（7.0 倍）。

**③ 消费者停止时连续 3 次查询**

```json
[{"status":"pending","attempts":0},{"status":"pending","attempts":0},{"status":"pending","attempts":0}]
```

**④ 启动消费者后**

```json
{"state_sequence":["pending","running","succeeded"],
 "final_status":"succeeded","final_attempts":1,"result_present":true,
 "required_resubmit":false}
```

消费者日志末行：

```
2026-11-04 18:24:34,786 INFO task=task_870a7f52bc3913ea status=succeeded attempts=1 result_written=True
```

终态响应示例（含结果，且状态接口仍只读）：

```json
{
  "task_id": "task_f31c9837a9eb89d9",
  "status": "succeeded",
  "attempts": 1,
  "result": { "score": 74, "feedback": "已批改 24 字作答；命中论证标记 2 个…", "created_at": "..." },
  "started_at": "...", "finished_at": "..."
}
```

## 一键复现（无需手工起服务）

```powershell
uv run python scripts/acceptance_async.py --out reports/evidence/async-acceptance.json
# 或
pwsh -File scripts/check-all.ps1 -Mode async
```

脚本在隔离 `CAMPUSCLAW_HOME` 起真实 HTTP 服务与独立消费者子进程，自动跑完三条判据，约 10 秒，不触碰项目 `data/`。

## 演示时可直接出示的证据

| 想证明什么 | 打开哪个文件 |
| --- | --- |
| 请求不再等待执行 | `reports/risk-transaction.md`（判据二）、`reports/evidence/async-acceptance.json` |
| 停消费者不丢任务 | `reports/risk-transaction.md` |
| 重复不产生重复结果 | `reports/risk-concurrency.md` |
| 七项安全自查与那条红 | `reports/security-precheck.md` |
| 门禁与资产基线 | `reports/security-baseline.md` |
| 审核记录 | `reports/review-01.md`、`docs/AI代码审核评审表.md` |
