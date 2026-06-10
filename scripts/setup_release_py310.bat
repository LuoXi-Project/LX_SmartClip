@echo off
setlocal
chcp 65001 > nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_release_py310.ps1" %*
exit /b %ERRORLEVEL%
