@echo off
setlocal
chcp 65001 > nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_release.ps1" %*
exit /b %ERRORLEVEL%
