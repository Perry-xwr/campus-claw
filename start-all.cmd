@echo off
rem One-click start for CampusClaw: app + index worker + MCP tool server + Qdrant.
rem Equivalent to: pwsh -File scripts\start-all.ps1
setlocal
chcp 65001 > NUL

set "PWSH=C:\Users\boyuan\AppData\Local\Microsoft\WindowsApps\pwsh.exe"
if not exist "%PWSH%" set "PWSH=pwsh"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-all.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
echo Stop everything:  pwsh -File scripts\stop-all.ps1
echo Logs:             .run\logs
if not "%CODE%"=="0" echo Script exit code: %CODE%  (see messages above and .run\logs)
echo.
pause
exit /b %CODE%
