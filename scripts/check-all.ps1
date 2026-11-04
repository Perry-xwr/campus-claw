<#
.SYNOPSIS
第 8 课一键检查入口（Windows / PowerShell 7）。

.EXAMPLE
pwsh -File scripts/check-all.ps1
pwsh -File scripts/check-all.ps1 -Mode security
pwsh -File scripts/check-all.ps1 -Mode async -Python C:\Path\To\python.exe
#>
param(
    [ValidateSet("all", "security", "async")]
    [string]$Mode = "all",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Python) {
    $candidate = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $candidate) { $Python = $candidate } else { $Python = "python" }
}

$evidence = Join-Path $root "reports\evidence"
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

$failed = 0

if ($Mode -in @("all", "security")) {
    Write-Host "=== [1/2] SEC-05 密钥扫描 + SEC-06 依赖基线 ===" -ForegroundColor Cyan
    & $Python "scripts\check_security.py" --out (Join-Path $evidence "security-baseline.json")
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if ($Mode -in @("all", "async")) {
    Write-Host "=== [2/2] 第 8 课三条判据复现 ===" -ForegroundColor Cyan
    & $Python "scripts\acceptance_async.py" --out (Join-Path $evidence "async-acceptance.json")
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if ($failed -eq 0) {
    Write-Host "全部检查通过；证据已归档到 reports/evidence/" -ForegroundColor Green
} else {
    Write-Host "存在未通过项，请查看上面的输出与 reports/evidence/ 中的 JSON" -ForegroundColor Red
}
exit $failed
