@echo off

setlocal EnableExtensions

chcp 65001 >nul



REM 从仓库根目录运行

cd /d "%~dp0"



set "BACKEND_PORT=18006"

set "BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%"

set "FRONTEND_URL=http://localhost:3000"



echo.

echo ========================================

echo   LX SmartClip - 开发环境准备与启动

echo ========================================

echo.



REM ---------- 1. 检查系统依赖（见 QUICKSTART.md）----------

echo [1/5] 检查系统依赖...



where python >nul 2>&1

if errorlevel 1 (

    echo [错误] 未找到 Python。请安装 Python 3.10+ 并加入 PATH。

    goto :fail

)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1

if errorlevel 1 (

    echo [错误] 需要 Python 3.10 或更高版本。

    python --version

    goto :fail

)

for /f "delims=" %%v in ('python --version 2^>^&1') do echo   Python: %%v



where node >nul 2>&1

if errorlevel 1 (

    echo [错误] 未找到 Node.js。请安装 Node.js 18+ 并加入 PATH。

    goto :fail

)

node -e "process.exit(parseInt(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)" >nul 2>&1

if errorlevel 1 (

    echo [错误] 需要 Node.js 18 或更高版本。

    node --version

    goto :fail

)

for /f "delims=" %%v in ('node --version 2^>^&1') do echo   Node.js: %%v



where npm >nul 2>&1

if errorlevel 1 (

    echo [错误] 未找到 npm（通常随 Node.js 安装）。

    goto :fail

)



where ffmpeg >nul 2>&1

if errorlevel 1 (

    echo [错误] 未找到 FFmpeg。请安装并加入 PATH（视频处理必需）。

    echo        下载: https://ffmpeg.org/download.html

    goto :fail

)

for /f "delims=" %%v in ('ffmpeg -version 2^>^&1 ^| findstr /i "ffmpeg version"') do (

    echo   FFmpeg: %%v

    goto :ffmpeg_ok

)

:ffmpeg_ok



where git >nul 2>&1

if errorlevel 1 (

    echo [提示] 未检测到 Git（可选，不影响本地开发启动）。

) else (

    for /f "delims=" %%v in ('git --version 2^>^&1') do echo   Git: %%v

)



REM ---------- 2. 创建工作目录 ----------

echo.

echo [2/5] 准备工作目录...

if not exist "backend\data" mkdir "backend\data"

if not exist "backend\storage" mkdir "backend\storage"

echo   backend\data、backend\storage 已就绪



REM ---------- 3. 后端 Python 虚拟环境 ----------

echo.

echo [3/5] 准备后端 Python 环境...

if not exist "backend\venv\Scripts\python.exe" (

    echo   创建虚拟环境 backend\venv ...

    pushd "backend"

    python -m venv venv

    if errorlevel 1 (

        echo [错误] 创建 venv 失败，请检查 Python 安装。

        popd

        goto :fail

    )

    popd

)



pushd "backend"

"venv\Scripts\python.exe" -m pip install --upgrade pip -q

if errorlevel 1 (

    echo [错误] pip 升级失败。

    popd

    goto :fail

)

echo   安装/同步 backend\requirements.txt ...

"venv\Scripts\python.exe" -m pip install -r requirements.txt

if errorlevel 1 (

    echo [错误] 后端依赖安装失败。

    popd

    goto :fail

)

popd

echo   后端依赖已就绪



REM ---------- 4. 前端 Node 依赖 ----------

echo.

echo [4/5] 准备前端 Node 环境...

pushd "frontend"

if not exist "node_modules" (

    echo   首次安装 npm 依赖...

) else (

    echo   同步 npm 依赖...

)

call npm install

if errorlevel 1 (

    echo [错误] npm install 失败。

    popd

    goto :fail

)

popd

echo   前端依赖已就绪



if not exist "frontend\.env.local" (

    echo   创建 frontend\.env.local ...

    > "frontend\.env.local" echo NEXT_PUBLIC_API_URL=%BACKEND_URL%

) else (

    findstr /i /c:"NEXT_PUBLIC_API_URL" "frontend\.env.local" >nul 2>&1

    if errorlevel 1 (

        echo   追加 NEXT_PUBLIC_API_URL 到 frontend\.env.local ...

        >> "frontend\.env.local" echo NEXT_PUBLIC_API_URL=%BACKEND_URL%

    )

)



REM ---------- 5. 启动服务 ----------

echo.

echo [5/5] 启动开发服务...

echo   后端: %BACKEND_URL%

echo   前端: %FRONTEND_URL%

echo   健康检查: %BACKEND_URL%/health

echo.



start "LX Backend" cmd /k "cd /d ""%~dp0backend"" && call venv\Scripts\activate.bat && uvicorn app.main:app --reload --host 127.0.0.1 --port %BACKEND_PORT%"



start "LX Frontend" cmd /k "cd /d ""%~dp0frontend"" && set NEXT_PUBLIC_API_URL=%BACKEND_URL%&& npm run dev"



echo [LX_SmartClip] 已启动两个终端窗口（后端 + 前端）。

echo.

endlocal

exit /b 0



:fail

echo.

pause

endlocal

exit /b 1

