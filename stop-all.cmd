@echo off
rem One-click stop for CampusClaw: local processes and Docker Compose containers.
rem Usage:
rem   stop-all.cmd                 stop everything (containers kept, fast restart)
rem   stop-all.cmd -KeepQdrant     keep the Qdrant container running
rem   stop-all.cmd -Down           remove containers and network (data volumes kept)
setlocal
chcp 65001 > NUL

set "PWSH=C:\Users\boyuan\AppData\Local\Microsoft\WindowsApps\pwsh.exe"
if not exist "%PWSH%" set "PWSH=pwsh"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-all.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
pause
exit /b %CODE%
