@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-task-floor-conformance.ps1" %*
exit /b %ERRORLEVEL%
