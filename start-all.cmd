@echo off
rem One-click start for CampusClaw.
rem Local mode (default): app + index worker + MCP server as local processes, Qdrant in Docker.
rem   start-all.cmd
rem   start-all.cmd -NoDocker          (keyword retrieval only)
rem Docker mode: whole stack in containers (app / worker / qdrant / mcp).
rem   start-all.cmd -Docker
rem   start-all.cmd -Docker -Rebuild   (rebuild image after code/dependency changes)
setlocal
chcp 65001 > NUL

set "PWSH=C:\Users\boyuan\AppData\Local\Microsoft\WindowsApps\pwsh.exe"
if not exist "%PWSH%" set "PWSH=pwsh"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-all.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
echo Stop everything:  stop-all.cmd   (or pwsh -File scripts\stop-all.ps1)
echo Logs:             .run\logs  (local mode)  /  docker compose logs -f app  (docker mode)
if not "%CODE%"=="0" echo Script exit code: %CODE%  (see messages above)
echo.
pause
exit /b %CODE%
