param(
    [string]$HostIP = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # ignore
}

function Remove-PathForce {
    param(
        [Parameter(Mandatory = $true)][string]$PathToRemove,
        [int]$Retries = 5,
        [int]$DelayMs = 300
    )

    if (-not (Test-Path $PathToRemove)) { return }

    for ($i = 1; $i -le $Retries; $i++) {
        try {
            if (Test-Path $PathToRemove -PathType Leaf) {
                attrib -r $PathToRemove 2>$null | Out-Null
            } else {
                attrib -r (Join-Path $PathToRemove "*") /s /d 2>$null | Out-Null
            }
            Remove-Item -Path $PathToRemove -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($i -eq $Retries) {
                throw "清理失败（可能文件被占用/杀软锁定）：$PathToRemove`n$($_.Exception.Message)"
            }
            Start-Sleep -Milliseconds $DelayMs
        }
    }
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $Root "backend"
$Entry = Join-Path $BackendDir "start_backend.py"
$DistDir = Join-Path $Root "dist"
$WorkDir = Join-Path $DistDir "_pyarmor_pyinstaller"
$ObfDir = Join-Path $WorkDir "obf"
$BuildDir = Join-Path $WorkDir "build"
$SpecDir = Join-Path $WorkDir "spec"
$PyinstallerDistDir = Join-Path $WorkDir "pyinstaller_dist"
$BackendOutDir = Join-Path $DistDir "backend"

$VenvPythonCandidates = @(
    (Join-Path $Root "venv\\Scripts\\python.exe"),
    (Join-Path $BackendDir "venv\\Scripts\\python.exe")
)
$Py = ($VenvPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Py) { $Py = "python" }

Write-Host "[backend] 检查入口文件..."
if (-not (Test-Path $Entry)) {
    throw "未找到后端入口: $Entry"
}

Write-Host "[backend] 清理 dist/backend ..."
if (-not (Test-Path $DistDir)) {
    New-Item -Path $DistDir -ItemType Directory -Force | Out-Null
}
if (Test-Path $BackendOutDir) {
    try {
        Remove-PathForce -PathToRemove $BackendOutDir
    } catch {
        $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $BackendOutDir = Join-Path $DistDir ("backend_" + $Stamp)
        Write-Host "[backend] 注意：dist/backend 被占用，改用新目录：$BackendOutDir"
    }
}
New-Item -Path $BackendOutDir -ItemType Directory -Force | Out-Null

Write-Host "[backend] 准备 PyArmor/PyInstaller 工作目录..."
if (Test-Path $WorkDir) {
    try {
        Remove-PathForce -PathToRemove $WorkDir
    } catch {
        $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $WorkDir = Join-Path $DistDir ("_pyarmor_pyinstaller_" + $Stamp)
        $ObfDir = Join-Path $WorkDir "obf"
        $BuildDir = Join-Path $WorkDir "build"
        $SpecDir = Join-Path $WorkDir "spec"
        $PyinstallerDistDir = Join-Path $WorkDir "pyinstaller_dist"
        Write-Host "[backend] 注意：旧工作目录无法清理（文件占用），改用新目录：$WorkDir"
    }
}
New-Item -Path $WorkDir -ItemType Directory -Force | Out-Null
New-Item -Path $ObfDir -ItemType Directory -Force | Out-Null
New-Item -Path $BuildDir -ItemType Directory -Force | Out-Null
New-Item -Path $SpecDir -ItemType Directory -Force | Out-Null
New-Item -Path $PyinstallerDistDir -ItemType Directory -Force | Out-Null

$FrontendStatic = Join-Path $BackendDir "app\\static\\frontend"
$StorageDir = Join-Path $BackendDir "storage"
$DataDir = Join-Path $BackendDir "data"

Push-Location $BackendDir
try {
    Write-Host "[backend] 检查 PyArmor / PyInstaller 依赖..."
    & $Py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pyarmor.cli') else 1)" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[backend] 未检测到 PyArmor，正在安装..."
        & $Py -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip 升级失败" }
        & $Py -m pip install --upgrade pyarmor
        if ($LASTEXITCODE -ne 0) { throw "PyArmor 安装失败" }
    }

    & $Py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[backend] 未检测到 PyInstaller，正在安装..."
        & $Py -m pip install --upgrade pyinstaller
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 安装失败" }
    }

    Write-Host "[backend] PyArmor 加密（递归）..."
    $PyarmorArgs = @(
        "-m", "pyarmor.cli", "gen",
        "-r",
        "-O", $ObfDir,
        "start_backend.py",
        "app"
    )
    & $Py @PyarmorArgs
    if ($LASTEXITCODE -ne 0) { throw "PyArmor 加密失败" }

    $ObfEntry = Join-Path $ObfDir "start_backend.py"
    if (-not (Test-Path $ObfEntry)) {
        throw "未找到加密后的入口文件: $ObfEntry"
    }

    Write-Host "[backend] PyInstaller 打包（onedir）..."
    Push-Location $ObfDir
    try {
        $AddData = @()
        if (Test-Path $FrontendStatic) { $AddData += @("--add-data", "$FrontendStatic;app/static/frontend") }
        if (Test-Path $StorageDir) { $AddData += @("--add-data", "$StorageDir;storage") }
        if (Test-Path $DataDir) { $AddData += @("--add-data", "$DataDir;data") }

        $CollectSubmodules = @(
            "uvicorn"
            "fastapi"
            "starlette"
            "anyio"
            "pydantic"
            "aiosqlite"
            "httpx"
            "requests"
            "openai"
            "whisper"
            "numpy"
            "edge_tts"
            "moviepy"
            "PIL"
            "scenedetect"
            "cryptography"
            "json_repair"
            "faiss"
        )

        $CollectAll = @(
            "uvicorn"
            "fastapi"
            "starlette"
            "pydantic"
            "aiosqlite"
            "numpy"
            "edge_tts"
            "whisper"
            "openai"
            "moviepy"
            "PIL"
            "cryptography"
            "scenedetect"
            "faiss"
        )

        $HiddenImports = @(
            "app.main"
            "uvicorn.main"
            "uvicorn.__main__"
        )

        $ForceCollectArgs = @()
        foreach ($m in $HiddenImports) { $ForceCollectArgs += @("--hidden-import", $m) }
        foreach ($p in $CollectSubmodules) { $ForceCollectArgs += @("--collect-submodules", $p) }
        foreach ($p in $CollectAll) { $ForceCollectArgs += @("--collect-all", $p) }

        $PyinstallerArgs = @(
            "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name", "lx_smartclip_backend",
            "--distpath", $PyinstallerDistDir,
            "--workpath", $BuildDir,
            "--specpath", $SpecDir,
            "--collect-submodules", "app",
            "--console",
            "start_backend.py"
        ) + $ForceCollectArgs + $AddData

        & $Py @PyinstallerArgs
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}

$ProducedDir = Join-Path $PyinstallerDistDir "lx_smartclip_backend"
if (-not (Test-Path $ProducedDir)) {
    throw "未找到 PyInstaller 产物目录: $ProducedDir"
}

Write-Host "[backend] 导出到 dist/backend ..."
Copy-Item -Path (Join-Path $ProducedDir "*") -Destination $BackendOutDir -Recurse -Force

Write-Host ""
Write-Host "后端构建完成（PyArmor + PyInstaller）：$BackendOutDir"
Write-Host "可执行文件：$(Join-Path $BackendOutDir 'lx_smartclip_backend.exe')"
Write-Host ""

