#Requires -Version 7.0
<#
.SYNOPSIS
  一键启动 CampusClaw 全部服务：主应用、索引 worker、MCP 工具服务、Qdrant。

.DESCRIPTION
  - 解释器优先级：-Python 参数 > 项目 .venv（uv sync 产物）> anaconda langdev；
  - 读取项目根目录 .env（只补齐缺失项，不覆盖当前进程已有的环境变量）；
  - 先停掉上一次由本脚本启动的进程（幂等，重复执行不会起多份）；
  - 端口被本项目的 Compose 容器占用时自动停掉该容器（例如旧的 campusclaw-app），
    避免健康检查打到旧镜像；其他进程占用则报错并提示换端口；
  - Qdrant 用 docker compose 起（Docker 未运行 / 加 -NoDocker 时跳过，向量检索不可用）；
  - MCP 工具服务需要 MCP_AUTH_TOKEN，脚本从 .env 读入再传给子进程；
  - 每个服务的输出写到 .run/logs/<服务>.log，PID 记在 .run/pids.json；
  - 启动后做健康检查（同时确认进程还活着），并打印访问地址与停止命令。

.EXAMPLE
  pwsh -File scripts/start-all.ps1

.EXAMPLE
  pwsh -File scripts/start-all.ps1 -NoDocker      # 不启动 Qdrant / worker，只用关键词检索

.EXAMPLE
  pwsh -File scripts/start-all.ps1 -AppPort 8099 -McpPort 8091

.EXAMPLE
  pwsh -File scripts/start-all.ps1 -Python "D:\conda\envs\langdev\python.exe"
#>
[CmdletBinding()]
param(
    # 留空时自动探测：优先项目 .venv（uv 管理），回落到本机 anaconda langdev。
    [string]$Python = "",
    [int]$AppPort = 0,
    [int]$McpPort = 0,
    [switch]$NoDocker
)

$ErrorActionPreference = "Stop"
# 关闭 Invoke-WebRequest 的进度条，避免刷屏
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$RunDir = Join-Path $Root ".run"
$LogDir = Join-Path $RunDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$PidFile = Join-Path $RunDir "pids.json"

# ---------------------------------------------------------------- 解释器探测
# 顺序：显式 -Python 参数 > 项目 .venv（uv sync 产物）> anaconda langdev。
# .venv 存在时说明本项目用 uv 管理依赖，此时不应再落到 conda 环境（两处依赖会漂移）。
$LangdevFallback = "E:\codetools\anaconda3\envs\langdev\python.exe"
if ([string]::IsNullOrWhiteSpace($Python)) {
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $Python = $venvPython
        Write-Host "[环境] 使用项目 .venv（uv）：$Python" -ForegroundColor DarkGray
    } else {
        $Python = $LangdevFallback
        Write-Host "[环境] 未找到 .venv，回落到 anaconda langdev：$Python" -ForegroundColor DarkGray
        Write-Host "       想改用 uv 管理：uv sync（详见 README「环境与依赖：用 uv 管理」）。" -ForegroundColor DarkGray
    }
}

if (-not (Test-Path $Python)) {
    Write-Host "[错误] 找不到 Python：$Python" -ForegroundColor Red
    Write-Host "       用 -Python <路径> 指定解释器，或先执行 uv sync 生成 .venv。" -ForegroundColor DarkGray
    exit 2
}

# ---------------------------------------------------------------- 工具函数
function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return 0 }
    $count = 0
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        $text = $line.Trim()
        if ($text -eq "" -or $text.StartsWith("#")) { continue }
        $idx = $text.IndexOf("=")
        if ($idx -lt 1) { continue }
        $key = $text.Substring(0, $idx).Trim()
        $value = $text.Substring($idx + 1).Trim()
        if ($value.Length -ge 2 -and (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        # 进程环境变量优先；.env 只补缺失项（与 config.load_project_dotenv 语义一致）
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($key))) {
            [Environment]::SetEnvironmentVariable($key, $value)
            $count++
        }
    }
    return $count
}

function Test-Docker {
    try {
        $null = docker info 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Test-HttpOk {
    param([string]$Url, [int]$TimeoutSec = 2)
    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -SkipHttpErrorCheck
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Get-PortOwners {
    param([int]$Port)
    try {
        return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        return @()
    }
}

function Clear-Port {
    param([int]$Port, [string]$PortParam)
    $owners = @(Get-PortOwners -Port $Port)
    if ($owners.Count -eq 0) { return $true }

    # 先看是不是本项目 Compose 里的容器占着（旧 campusclaw-app 会随 Docker 自动重启）
    if (Test-Docker) {
        $rows = docker compose ps --format "{{.Service}}|{{.Name}}|{{.Ports}}" 2>&1
        if ($LASTEXITCODE -eq 0) {
            foreach ($row in $rows) {
                $parts = $row -split "\|"
                if ($parts.Count -ge 3 -and $parts[2] -match ":$Port->") {
                    Write-Host ("[端口] {0} 被 Compose 服务 {1} 占用，先停止该容器" -f $Port, $parts[0]) -ForegroundColor Yellow
                    $null = docker compose stop $parts[0] 2>&1
                    Start-Sleep -Seconds 2
                }
            }
            $owners = @(Get-PortOwners -Port $Port)
            if ($owners.Count -eq 0) { return $true }
        }
    }

    $detail = ($owners | ForEach-Object {
            $process = Get-Process -Id $_ -ErrorAction SilentlyContinue
            if ($process) { "{0}(PID {1})" -f $process.ProcessName, $_ } else { "PID $_" }
        }) -join "、"
    Write-Host ("[错误] 端口 {0} 仍被占用：{1}" -f $Port, $detail) -ForegroundColor Red
    Write-Host ("       先停止占用进程，或用 -{0} <另一个端口> 启动。" -f $PortParam) -ForegroundColor DarkGray
    return $false
}

function Start-ServiceProcess {
    param(
        [string]$Name,
        [string]$Arguments,
        [string]$WorkingDirectory
    )
    $stdout = Join-Path $LogDir "$Name.log"
    $stderr = Join-Path $LogDir "$Name.err.log"
    foreach ($file in @($stdout, $stderr)) {
        if (Test-Path $file) { Remove-Item $file -Force }
    }
    $process = Start-Process -FilePath $Python -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Write-Host ("  ├─ {0,-6} 已启动（PID {1}）" -f $Name, $process.Id) -ForegroundColor DarkGray
    return $process
}

function Wait-Service {
    param(
        [string]$Url,
        [int]$Seconds,
        [string]$Name,
        [int]$ProcessId
    )
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            Write-Host "[失败] $Name 进程已退出（见日志）" -ForegroundColor Red
            return $false
        }
        if (Test-HttpOk -Url $Url) { return $true }
        Start-Sleep -Milliseconds 400
    }
    Write-Host "[超时] $Name 未在 ${Seconds}s 内就绪：$Url" -ForegroundColor Yellow
    return $false
}

# ---------------------------------------------------------------- 0. 清理旧实例
$stopScript = Join-Path $PSScriptRoot "stop-all.ps1"
if (Test-Path $PidFile) {
    Write-Host "检测到上次启动的实例，先停止……" -ForegroundColor DarkGray
    & $stopScript -Quiet
}

# ---------------------------------------------------------------- 1. 读取配置
$loaded = Import-DotEnv (Join-Path $Root ".env")
Write-Host ("读取 .env：补入 {0} 个变量" -f $loaded) -ForegroundColor DarkGray

if ($AppPort -le 0) { $AppPort = if ($env:PORT) { [int]$env:PORT } else { 8080 } }
if ($McpPort -le 0) { $McpPort = if ($env:MCP_PORT) { [int]$env:MCP_PORT } else { 8090 } }
$env:PORT = "$AppPort"
$env:MCP_PORT = "$McpPort"
$qdrantUrl = if ($env:QDRANT_URL) { $env:QDRANT_URL.TrimEnd("/") } else { "http://127.0.0.1:6333" }

$mcpToken = $env:MCP_AUTH_TOKEN
if ([string]::IsNullOrWhiteSpace($mcpToken)) {
    Write-Host "[警告] .env 里没有 MCP_AUTH_TOKEN，MCP 工具服务会启动失败。" -ForegroundColor Yellow
    Write-Host "       在项目根 .env 里加一行 MCP_AUTH_TOKEN=<你的令牌> 后重试。" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host @"
CampusClaw 一键启动
  项目目录  $Root
  Python    $Python
  主应用    http://127.0.0.1:$AppPort
  MCP 服务  http://127.0.0.1:$McpPort
"@ -ForegroundColor Cyan
Write-Host ""

$pids = [ordered]@{ python = $Python; started_at = (Get-Date).ToString("s") }
$failed = $false

# ---------------------------------------------------------------- 2. Qdrant（可选）
$qdrantReady = $false
if ($NoDocker) {
    Write-Host "[跳过] Qdrant（-NoDocker）：向量/混合检索不可用，关键词检索照常。" -ForegroundColor Yellow
} else {
    Write-Host "启动 Qdrant（docker compose）……" -ForegroundColor Cyan
    if (-not (Test-Docker)) {
        Write-Host "[跳过] Docker 未运行：请先启动 Docker Desktop；本轮只用关键词检索。" -ForegroundColor Yellow
        Write-Host "       之后想启用向量检索：启动 Docker 后重跑本脚本。" -ForegroundColor DarkGray
    } else {
        # --quiet-pull：已有镜像时静默；首次拉取也不刷进度条
        $composeOutput = docker compose up -d --quiet-pull qdrant 2>&1
        if ($LASTEXITCODE -ne 0) {
            $composeOutput | Select-Object -Last 5 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
        }
        if ($LASTEXITCODE -eq 0) {
            $deadline = (Get-Date).AddSeconds(40)
            while ((Get-Date) -lt $deadline -and -not $qdrantReady) {
                $qdrantReady = Test-HttpOk -Url "$qdrantUrl/readyz"
                if (-not $qdrantReady) { Start-Sleep -Milliseconds 500 }
            }
        }
        if ($qdrantReady) {
            $pids["qdrant"] = "compose"
            Write-Host "  ├─ qdrant 已就绪" -ForegroundColor DarkGray
        } else {
            Write-Host "[警告] Qdrant 未就绪：镜像拉取失败或端口被占用；本轮跳过索引 worker。" -ForegroundColor Yellow
        }
    }
}

# ---------------------------------------------------------------- 3. 索引 worker
if ($qdrantReady) {
    Write-Host "启动索引 worker……" -ForegroundColor Cyan
    $worker = Start-ServiceProcess -Name "worker" -Arguments "-m campusclaw.index_worker" -WorkingDirectory $Root
    $pids["worker"] = $worker.Id
} else {
    Write-Host "[跳过] 索引 worker（没有可用的 Qdrant）" -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 4. MCP 工具服务
Write-Host "启动 MCP 工具服务……" -ForegroundColor Cyan
$mcpOk = $false
$mcp = $null
if (Clear-Port -Port $McpPort -PortParam "McpPort") {
    $mcp = Start-ServiceProcess -Name "mcp" -Arguments "-m mcp_server" -WorkingDirectory (Join-Path $Root "mcp-server")
    $pids["mcp"] = $mcp.Id
} else {
    $failed = $true
}

# ---------------------------------------------------------------- 5. 主应用
Write-Host "启动主应用……" -ForegroundColor Cyan
$appProc = $null
if (Clear-Port -Port $AppPort -PortParam "AppPort") {
    $appProc = Start-ServiceProcess -Name "app" -Arguments "app.py" -WorkingDirectory $Root
    $pids["app"] = $appProc.Id
} else {
    $failed = $true
}

$pids | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8

# ---------------------------------------------------------------- 6. 健康检查
function Show-LogTail {
    param([string]$Name)
    foreach ($file in @("$Name.log", "$Name.err.log")) {
        $path = Join-Path $LogDir $file
        if ((Test-Path $path) -and ((Get-Item $path).Length -gt 0)) {
            Write-Host ("--- {0} ---" -f $file) -ForegroundColor DarkGray
            Get-Content $path -Tail 12 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
        }
    }
}

if ($appProc) {
    Write-Host ""
    Write-Host "等待服务就绪……" -ForegroundColor Cyan
    if (-not (Wait-Service -Url "http://127.0.0.1:$AppPort/health" -Seconds 40 -Name "主应用" -ProcessId $appProc.Id)) {
        $failed = $true
        Write-Host "[失败] 主应用未就绪。常见原因：端口 $AppPort 被占用、数据库迁移失败。" -ForegroundColor Red
        Show-LogTail "app"
    }
}
if ($mcp) {
    $mcpOk = Wait-Service -Url "http://127.0.0.1:$McpPort/health" -Seconds 20 -Name "MCP 工具服务" -ProcessId $mcp.Id
    if (-not $mcpOk) {
        $failed = $true
        Write-Host "[失败] MCP 工具服务未就绪。常见原因：缺少 MCP_AUTH_TOKEN、端口 $McpPort 被占用。" -ForegroundColor Red
        Show-LogTail "mcp"
    }
}

# ---------------------------------------------------------------- 7. 汇总
Write-Host ""
if (-not $failed) {
    $vectorLine = if ($qdrantReady) {
        "  向量检索    已启用（worker 在跑；材料需在「知识检索」页重建索引）"
    } else {
        "  向量检索    未启用（关键词检索与解题助手照常可用）"
    }
    $qdrantLine = if ($qdrantReady) { "  Qdrant      $qdrantUrl/dashboard" } else { "" }
    Write-Host @"
全部就绪
  登录页      http://127.0.0.1:$AppPort/login
  解题助手    http://127.0.0.1:$AppPort/tutor
  MCP 管理    http://127.0.0.1:$AppPort/mcp
  Swagger     http://127.0.0.1:$AppPort/swagger/index.html
  MCP 健康    http://127.0.0.1:$McpPort/health
$qdrantLine
$vectorLine

日志目录    $LogDir
停止全部    pwsh -File scripts/stop-all.ps1
"@ -ForegroundColor Green
    exit 0
}

Write-Host "启动未完全成功：仍可用 pwsh -File scripts/stop-all.ps1 清理。" -ForegroundColor Red
exit 1
