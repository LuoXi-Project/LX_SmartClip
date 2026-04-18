@echo off
setlocal

REM Ensure script runs from repository root
cd /d "%~dp0"

echo [LX_SmartClip] Preparing backend environment...
if not exist "backend\venv\Scripts\activate.bat" (
    echo [backend] venv not found, creating...
    pushd "backend"
    python -m venv venv
    if errorlevel 1 (
        echo [backend] Failed to create venv. Check Python installation.
        popd
        pause
        exit /b 1
    )
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [backend] Failed to install requirements.
        popd
        pause
        exit /b 1
    )
    popd
)

echo [LX_SmartClip] Preparing frontend dependencies...
if not exist "frontend\node_modules" (
    echo [frontend] node_modules not found, installing...
    pushd "frontend"
    npm install
    if errorlevel 1 (
        echo [frontend] npm install failed.
        popd
        pause
        exit /b 1
    )
    popd
)

echo [LX_SmartClip] Starting backend on http://127.0.0.1:8000 ...
start "LX Backend" cmd /k "cd /d ""%~dp0backend"" && call venv\Scripts\activate.bat && uvicorn app.main:app --reload --host 127.0.0.1 --port 8001"

echo [LX_SmartClip] Starting frontend on http://localhost:3000 ...
start "LX Frontend" cmd /k "cd /d ""%~dp0frontend"" && npm run dev"

echo [LX_SmartClip] Done. Two terminal windows launched.
endlocal
