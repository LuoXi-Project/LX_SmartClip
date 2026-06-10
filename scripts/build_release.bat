@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul

set "ROOT=%~dp0.."
set "FRONTEND_DIR=%ROOT%\frontend"
set "FRONTEND_OUT=%FRONTEND_DIR%\out"
set "BACKEND_WEB_DIR=%ROOT%\backend\app\static\frontend"
set "DIST_DIR=%ROOT%\dist"
set "BACKEND_BUILDER=%LX_BACKEND_BUILDER%"
if "%BACKEND_BUILDER%"=="" set "BACKEND_BUILDER=pyarmor"
if not "%~1"=="" set "BACKEND_BUILDER=%~1"
set "BUILD_FRONTEND=1"
if /I "%~2"=="skip-frontend" set "BUILD_FRONTEND=0"
if /I "%~2"=="--skip-frontend" set "BUILD_FRONTEND=0"

if "%BUILD_FRONTEND%"=="1" (
  echo [1/2] 检查目录...
  if not exist "%FRONTEND_DIR%\package.json" (
    echo 错误：未找到前端目录或 package.json: "%FRONTEND_DIR%"
    exit /b 1
  )

  echo [1/2] 安装前端依赖...
  cd /d "%FRONTEND_DIR%"
  call npm install
  if errorlevel 1 (
    echo 错误：npm install 失败
    exit /b 1
  )

  echo [1/2] 构建前端导出产物...
  call npm run build
  if errorlevel 1 (
    echo 错误：npm run build 失败
    exit /b 1
  )

  if not exist "%FRONTEND_OUT%\index.html" (
    echo 错误：未找到导出产物 "%FRONTEND_OUT%\index.html"
    exit /b 1
  )

  echo [1/2] 拷贝构建产物到后端静态目录...
  if exist "%BACKEND_WEB_DIR%" rmdir /s /q "%BACKEND_WEB_DIR%"
  mkdir "%BACKEND_WEB_DIR%"
  xcopy "%FRONTEND_OUT%\*" "%BACKEND_WEB_DIR%\" /E /I /Y > nul
  if errorlevel 1 (
    echo 错误：拷贝静态文件失败
    exit /b 1
  )
) else (
  echo [1/2] 跳过前端构建（参数: %~2）
)

echo [2/2] 构建后端并导出 dist/... （%BACKEND_BUILDER%）
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if /I "%BACKEND_BUILDER%"=="pyarmor" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_backend_pyarmor_pyinstaller.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_backend_nuitka.ps1"
)
if errorlevel 1 (
  echo 错误：后端构建失败（%BACKEND_BUILDER%）
  exit /b 1
)

echo.
echo Build completed.
if "%BUILD_FRONTEND%"=="1" (
  echo Frontend output: "%FRONTEND_OUT%"
  echo Backend static dir: "%BACKEND_WEB_DIR%"
) else (
  echo Frontend build: skipped
)
echo Dist dir: "%DIST_DIR%"
echo.
if exist "%DIST_DIR%\.backend_out" (
  set /p BACKEND_OUT=<"%DIST_DIR%\.backend_out"
  echo Release backend: "!BACKEND_OUT!\lx_smartclip_backend.exe"
) else (
  echo Release backend: "%DIST_DIR%\backend\lx_smartclip_backend.exe"
)
exit /b 0
