@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-anchor-crate-4060-smoke.ps1" %*
exit /b %ERRORLEVEL%
