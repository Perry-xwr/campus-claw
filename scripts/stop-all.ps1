#Requires -Version 7.0
<#
.SYNOPSIS
  停止由 scripts/start-all.ps1 启动的全部服务（主应用 / MCP / worker，以及 Qdrant 容器）。

.DESCRIPTION
  按 .run/pids.json 记录的 PID 依次停止进程，再 `docker compose stop qdrant`。
  只动本脚本记录过的进程，不会误杀手动启动的其他程序。幂等：没有实例时直接返回。

.EXAMPLE
  pwsh -File scripts/stop-all.ps1

.EXAMPLE
  pwsh -File scripts/stop-all.ps1 -KeepQdrant   # 保留 Qdrant 容器，加快下次启动
#>
[CmdletBinding()]
param(
    [switch]$Quiet,
    [switch]$KeepQdrant
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$PidFile = Join-Path $Root ".run\pids.json"

function Say {
    param([string]$Text, [string]$Color = "Gray")
    if (-not $Quiet) { Write-Host $Text -ForegroundColor $Color }
}

if (-not (Test-Path $PidFile)) {
    Say "没有记录在案的运行实例（.run/pids.json 不存在）。" "DarkGray"
} else {
    $data = Get-Content $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json
    # 先停依赖方，再停被依赖方：app → mcp → worker
    foreach ($name in @("app", "mcp", "worker")) {
        $procId = $data.$name
        if (-not $procId) { continue }
        $process = Get-Process -Id ([int]$procId) -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            Say ("  {0,-6} 已退出（PID {1}）" -f $name, $procId) "DarkGray"
            continue
        }
        try {
            Stop-Process -Id ([int]$procId) -Force -ErrorAction Stop
            Say ("  {0,-6} 已停止（PID {1}）" -f $name, $procId) "DarkGray"
        } catch {
            Say ("  {0,-6} 停止失败：{1}" -f $name, $_.Exception.Message) "Yellow"
        }
    }
    Remove-Item $PidFile -Force
}

if (-not $KeepQdrant) {
    try {
        $null = docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            $output = docker compose stop qdrant 2>&1
            if ($LASTEXITCODE -eq 0) {
                Say "  qdrant 已停止" "DarkGray"
            } else {
                Say ("  qdrant 停止未成功：{0}" -f ($output -join " ")) "Yellow"
            }
        } else {
            Say "  Docker 未运行，跳过 qdrant" "DarkGray"
        }
    } catch {
        Say "  Docker 不可用，跳过 qdrant" "DarkGray"
    }
} else {
    Say "  保留 qdrant 容器（-KeepQdrant）" "DarkGray"
}

Say "已清理完毕。" "Green"
