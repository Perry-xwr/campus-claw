#Requires -Version 7.0
<#
.SYNOPSIS
  停止 CampusClaw 的全部服务：本机进程（app / mcp / worker）与 Docker Compose 里的容器。

.DESCRIPTION
  两种启动方式都能收尾：
  - 本机进程：按 .run/pids.json 记录的 PID 停止，只动本脚本记录过的进程，不会误杀手动启动的其它程序；
  - 容器：本机模式通常只跑了 qdrant；容器模式（start-all -Docker）会连带 app / worker / mcp 一起停。

  默认用 stop：容器保留（下次启动快）。加 -Down 则移除容器与网络，数据卷与宿主机
  ./data、./uploads 目录不受影响。幂等：没有实例时直接返回。

.EXAMPLE
  pwsh -File scripts/stop-all.ps1

.EXAMPLE
  pwsh -File scripts/stop-all.ps1 -KeepQdrant    # 保留 Qdrant，加快下次启动

.EXAMPLE
  pwsh -File scripts/stop-all.ps1 -Down          # 移除容器与网络（数据保留）
#>
[CmdletBinding()]
param(
    [switch]$Quiet,
    [switch]$KeepQdrant,
    [switch]$Down
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$PidFile = Join-Path $Root ".run\pids.json"

function Say {
    param([string]$Text, [string]$Color = "Gray")
    if (-not $Quiet) { Write-Host $Text -ForegroundColor $Color }
}

function Test-DockerRunning {
    try {
        $null = docker info 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-RunningComposeServices {
    # 返回当前 compose 项目里处于 running 的服务名列表。
    try {
        $output = docker compose ps --services --filter "status=running" 2>$null
        if ($LASTEXITCODE -ne 0) { return @() }
        return @($output | Where-Object { $_ -and $_.Trim() -ne "" } | ForEach-Object { $_.Trim() })
    } catch {
        return @()
    }
}

# ---------------------------------------------------------------- 1. 本机进程
if (-not (Test-Path $PidFile)) {
    Say "没有记录在案的本机进程（.run/pids.json 不存在）。" "DarkGray"
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

# ---------------------------------------------------------------- 2. 容器
if (-not (Test-DockerRunning)) {
    Say "  Docker 未运行，跳过容器" "DarkGray"
    Say "已清理完毕。" "Green"
    return
}

$services = @(Get-RunningComposeServices)
if ($services.Count -eq 0) {
    Say "  没有运行中的 Compose 容器" "DarkGray"
    Say "已清理完毕。" "Green"
    return
}

if ($Down) {
    if ($KeepQdrant) {
        Say "  -Down 会移除整个 Compose 项目的容器，-KeepQdrant 不生效（数据卷仍保留）" "Yellow"
    }
    Say ("  移除容器与网络：{0}" -f ($services -join "、")) "DarkGray"
    $output = docker compose down 2>&1
    if ($LASTEXITCODE -eq 0) {
        Say "  容器已移除（数据卷与 ./data、./uploads 保留）" "DarkGray"
    } else {
        Say ("  移除未成功：{0}" -f (($output | Select-Object -Last 3) -join " ")) "Yellow"
    }
    Say "已清理完毕。" "Green"
    return
}

if ($KeepQdrant) {
    $targets = @($services | Where-Object { $_ -ne "qdrant" })
    if ($targets.Count -gt 0) {
        $output = docker compose stop $targets 2>&1
        if ($LASTEXITCODE -eq 0) {
            Say ("  {0} 已停止" -f ($targets -join "、")) "DarkGray"
        } else {
            Say ("  停止未成功：{0}" -f (($output | Select-Object -Last 3) -join " ")) "Yellow"
        }
    }
    Say "  保留 qdrant 容器（-KeepQdrant）" "DarkGray"
} else {
    $output = docker compose stop 2>&1
    if ($LASTEXITCODE -eq 0) {
        Say ("  {0} 已停止" -f ($services -join "、")) "DarkGray"
    } else {
        Say ("  停止未成功：{0}" -f (($output | Select-Object -Last 3) -join " ")) "Yellow"
    }
}

Say "已清理完毕。" "Green"
