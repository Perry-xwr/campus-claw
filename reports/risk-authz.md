# 高风险三查 · 权限 · CampusClaw

> 对应 `reports/security-precheck.md` 的 SEC-02。复测命令可在演示机器原样再跑；凭据为仓库公开的内置演示口令，Bearer 令牌运行时动态签发。

- **用什么手段查**：接口用例——用 A 班学生 `student_a1` 的令牌访问 B 班资源（跨班访问），并用 B 班学生 `student_b1` 的身份检索 A 班知识库独有内容（跨班检索）；同时用本班检索做对照组，排除「检索整体失效」造成的假绿。
- **查了什么**：① 跨班讲义是否可读；② 跨班知识库检索是否泄漏别班内容；③ 检索能力本身是否可用。
- **判据**：跨班资源访问一律 **404**（先按 `class_id` 过滤再取数，跨班与不存在不可区分）；跨班检索返回空结果，**条数为 0**；本班对照检索 **≥ 1 条**。
- **结果**：跨班访问 `GET /api/materials/2 → 404`；A1 检索 `B_ONLY_SEED → 0 条`；B1 检索 `A_ONLY_SEED → 0 条`；对照组 A1 检索本班 `A_ONLY_SEED → 1 条`。三条均符合判据，**绿**。
- **实现依据**：身份 `class_id` 只从服务端会话表取得（`sessions.USER_COLUMNS` JOIN `users/classes`），不信任客户端 `class_id`；材料查询 `materials.py` 带 `class_id` 条件；检索 `retrieval.py` 的 `_ACTIVE_CHUNK` / `keyword_search` 均带 `class_id` 过滤，向量侧 Qdrant 也按 `class_id` 加 filter；新增的异步任务 `task_db.status_for` 同样按 `class_id` 过滤，跨班与不存在统一 404。

## 复测命令（PowerShell 7，原样复制）

```powershell
# 在项目根目录执行；服务按 README 启动在 8080
$base = "http://127.0.0.1:8080"
$hdr  = @{ "Content-Type" = "application/json" }

$login = Invoke-RestMethod -Uri "$base/api/login" -Method Post -Headers $hdr `
  -Body '{"username":"student_a1","password":"StudentA1#2026"}'
$token = $login.token
$h = @{ Authorization = "Bearer $token" }

# 取 B 班讲义 ID（避免把示例里的 id=2 当成固定值）
$bid = & ".\.venv\Scripts\python.exe" -c "import sqlite3;print(sqlite3.connect('data/app.db').execute('SELECT id FROM materials WHERE class_id=2 LIMIT 1').fetchone()[0])"

# ① 跨班访问：期望 404
try {
  $r = Invoke-WebRequest -Uri "$base/api/materials/$bid" -Headers $h -UseBasicParsing
  $r.StatusCode
} catch {
  [int]$_.Exception.Response.StatusCode   # 期望输出：404
}

# ② 跨班检索：期望 hits 为空数组
Invoke-RestMethod -Uri "$base/api/search" -Method Post -Headers ($h + @{ "Content-Type" = "application/json" }) `
  -Body '{"query":"B_ONLY_SEED","mode":"keyword","limit":5}' | ConvertTo-Json -Depth 6
# 期望输出中 "hits": []  且 "message" 为未找到提示

# ③ 对照组：本班检索应有结果
Invoke-RestMethod -Uri "$base/api/search" -Method Post -Headers ($h + @{ "Content-Type" = "application/json" }) `
  -Body '{"query":"A_ONLY_SEED","mode":"keyword","limit":5}' | ConvertTo-Json -Depth 6
# 期望 "hits" 至少 1 条，且每条 material 属于 A 班
```

## 一键复现（不依赖手工起服务）

```powershell
uv run python scripts/acceptance_security.py --out reports/evidence/security-precheck.json
```

该脚本在隔离 `CAMPUSCLAW_HOME` 里起真实 HTTP 服务，自动完成上述三组检索与跨班访问，把返回码与命中条数写进 JSON 的 `SEC-02` 条；两次独立运行的输出分别为
`reports/evidence/security-precheck.json` 与 `reports/evidence/security-precheck-recheck.json`，判定一致。

## 与后续课次的关系

本文件是最终项目报告「高风险三查 · 权限」的直接素材；`reports/security-precheck.md` 中的受保护接口清单与写入类接口清单，后续课次会直接拿来做权限收紧的对照表。
