<#
.SYNOPSIS
第 8–10 课一键检查入口（Windows / PowerShell 5.1 或 7）。

.EXAMPLE
pwsh -File scripts/check-all.ps1
pwsh -File scripts/check-all.ps1 -Mode security
pwsh -File scripts/check-all.ps1 -Mode async -Python C:\Path\To\python.exe
#>
param(
    [ValidateSet("all", "security", "async", "apitest", "audit", "observe", "compose")]
    [string]$Mode = "all",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Windows PowerShell 5.1 会把原生命令写到 stderr 的内容（例如 Flask 的访问日志）
# 当成终止错误，配合上面的 Stop 会让门禁在第一项就中断。判定只应看退出码，
# 因此调用期间临时放宽，结束后还原。
function Invoke-Check {
    param([string]$Script, [string[]]$ScriptArgs = @())
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Python $Script @ScriptArgs
    } finally {
        $ErrorActionPreference = $previous
    }
}

if (-not $Python) {
    $candidate = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $candidate) { $Python = $candidate } else { $Python = "python" }
}

$evidence = Join-Path $root "reports\evidence"
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

$failed = 0

if ($Mode -in @("all", "security")) {
    Write-Host "=== [1/6] SEC-05 密钥扫描 + SEC-06 依赖基线 ===" -ForegroundColor Cyan
    Invoke-Check "scripts\check_security.py" @("--out", (Join-Path $evidence "security-baseline.json"))
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if ($Mode -in @("all", "async")) {
    Write-Host "=== [2/6] 第 8 课三条判据复现 ===" -ForegroundColor Cyan
    Invoke-Check "scripts\acceptance_async.py" @("--out", (Join-Path $evidence "async-acceptance.json"))
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if ($Mode -in @("all", "apitest")) {
    Write-Host "=== [3/6] 第 9 课注入三件套（SQL / XSS / CSRF）===" -ForegroundColor Cyan
    Invoke-Check "apitest\run_all.py" @("--no-report")
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if ($Mode -in @("all", "audit")) {
    Write-Host "=== [4/6] SEC-07 审计日志七列回查 ===" -ForegroundColor Cyan
    # 干净环境没有运行库时 --allow-empty 只跳过数据断言，结构断言（七列是否齐备）仍生效。
    $auditDb = "data\app.db"
    if ($env:CAMPUSCLAW_AUDIT_DB) { $auditDb = $env:CAMPUSCLAW_AUDIT_DB }
    Invoke-Check "scripts\audit_recheck.py" @("--db", $auditDb, "--out", "reports\audit-recheck.md", "--allow-empty")
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if ($Mode -in @("all", "observe")) {
    Write-Host "=== [5/6] 第 10 课运行观测告警判定 ===" -ForegroundColor Cyan
    # critical 级告警即判红；干净环境没有库时脚本按跳过处理，不影响结论。
    $observeDb = "data\app.db"
    if ($env:CAMPUSCLAW_AUDIT_DB) { $observeDb = $env:CAMPUSCLAW_AUDIT_DB }
    Invoke-Check "scripts\check_observe.py" @("--db", $observeDb, "--out", (Join-Path $evidence "observe.json"))
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if ($Mode -in @("all", "compose")) {
    Write-Host "=== [6/6] 容器配置静态校验（不需要 Docker）===" -ForegroundColor Cyan
    # compose / Dockerfile 的配置类错误（悬空依赖、COPY 缺源、端口不符、版本越界）
    # 不需要 Docker 就能查；实跑 `docker compose up` 由人工步骤补。
    Invoke-Check "scripts\check_compose.py" @("--out", (Join-Path $evidence "compose-static.json"))
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if ($failed -eq 0) {
    Write-Host "全部检查通过；证据已归档到 reports/evidence/" -ForegroundColor Green
} else {
    Write-Host "存在未通过项，请查看上面的输出与 reports/evidence/ 中的 JSON" -ForegroundColor Red
}
exit $failed
