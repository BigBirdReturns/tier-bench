@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-anchor-crate-lab.ps1" %*
exit /b %ERRORLEVEL%
