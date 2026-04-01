@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul

set "ROOT=%~dp0.."
set "FRONTEND_DIR=%ROOT%\frontend"
set "FRONTEND_OUT=%FRONTEND_DIR%\out"
set "BACKEND_WEB_DIR=%ROOT%\backend\app\static\frontend"

echo [1/4] 检查目录...
if not exist "%FRONTEND_DIR%\package.json" (
  echo 错误：未找到前端目录或 package.json: "%FRONTEND_DIR%"
  exit /b 1
)

echo [2/4] 安装前端依赖...
cd /d "%FRONTEND_DIR%"
call npm install
if errorlevel 1 (
  echo 错误：npm install 失败
  exit /b 1
)

echo [3/4] 构建前端导出产物...
call npm run build
if errorlevel 1 (
  echo 错误：npm run build 失败
  exit /b 1
)

if not exist "%FRONTEND_OUT%\index.html" (
  echo 错误：未找到导出产物 "%FRONTEND_OUT%\index.html"
  exit /b 1
)

echo [4/4] 拷贝构建产物到后端静态目录...
if exist "%BACKEND_WEB_DIR%" rmdir /s /q "%BACKEND_WEB_DIR%"
mkdir "%BACKEND_WEB_DIR%"
xcopy "%FRONTEND_OUT%\*" "%BACKEND_WEB_DIR%\" /E /I /Y > nul
if errorlevel 1 (
  echo 错误：拷贝静态文件失败
  exit /b 1
)

echo.
echo Build completed.
echo Frontend output: "%FRONTEND_OUT%"
echo Backend static dir: "%BACKEND_WEB_DIR%"
echo.
echo Start backend and open http://127.0.0.1:8000
exit /b 0
