chcp 65001 > $null
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

$AppName = "lx_smartclip_backend"
# PyInstaller 的 --name 会参与 build 子目录/产物目录命名；为避免 Unicode 路径在部分环境下异常，这里用英文内部名
$PyinstallerName = "lx_smartclip_backend"

$LogoIco = Join-Path $Root "frontend\logo.ico"
# 仓库根目录 ffmpeg\bin（含 ffmpeg.exe / ffprobe.exe，见 ffmpeg 官网 Windows builds）
$FfmpegBinDir = Join-Path $Root "ffmpeg\bin"

$SecretPy = Join-Path $BackendDir "secret.py"
$ConfigJson = Join-Path $BackendDir "config.json"

$VenvPythonCandidates = @(
    (Join-Path $Root "venv\\Scripts\\python.exe"),
    (Join-Path $BackendDir "venv\\Scripts\\python.exe")
)
$Py = ($VenvPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Py) { $Py = "python" }

Write-Host "`[backend`] 检查入口文件..."
if (-not (Test-Path $Entry)) {
    throw "未找到后端入口: $Entry"
}

Write-Host "`[backend`] 清理 dist/backend ..."
if (-not (Test-Path $DistDir)) {
    New-Item -Path $DistDir -ItemType Directory -Force | Out-Null
}
if (Test-Path $BackendOutDir) {
    try {
        Remove-PathForce -PathToRemove $BackendOutDir
    } catch {
        $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $BackendOutDir = Join-Path $DistDir ("backend_" + $Stamp)
        Write-Host "`[backend`] 注意：dist/backend 被占用，改用新目录：$BackendOutDir"
    }
}
New-Item -Path $BackendOutDir -ItemType Directory -Force | Out-Null

Write-Host "`[backend`] 准备 PyArmor/PyInstaller 工作目录..."
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
        Write-Host "`[backend`] 注意：旧工作目录无法清理（文件占用），改用新目录：$WorkDir"
    }
}
New-Item -Path $WorkDir -ItemType Directory -Force | Out-Null
New-Item -Path $ObfDir -ItemType Directory -Force | Out-Null
New-Item -Path $BuildDir -ItemType Directory -Force | Out-Null
New-Item -Path $SpecDir -ItemType Directory -Force | Out-Null
New-Item -Path $PyinstallerDistDir -ItemType Directory -Force | Out-Null

$FrontendStatic = Join-Path $BackendDir "app\\static\\frontend"

Push-Location $BackendDir
try {
    Write-Host "`[backend`] 检查 PyArmor / PyInstaller 依赖..."
    & $Py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pyarmor.cli') else 1)" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`[backend`] 未检测到 PyArmor，正在安装..."
        & $Py -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip 升级失败" }
        & $Py -m pip install --upgrade pyarmor
        if ($LASTEXITCODE -ne 0) { throw "PyArmor 安装失败" }
    }

    & $Py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`[backend`] 未检测到 PyInstaller，正在安装..."
        & $Py -m pip install --upgrade pyinstaller
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 安装失败" }
    }

    # 官方补充 hooks，改善 imageio / moviepy 等在 frozen 下的数据与元数据收集
    & $Py -m pip install --upgrade "pyinstaller-hooks-contrib"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`[backend`] 警告: pyinstaller-hooks-contrib 安装失败（可忽略，运行时仍有 metadata 兜底）"
    }

    Write-Host "`[backend`] 去除 Python 源文件 UTF-8 BOM（避免 PyArmor ast.parse 失败）..."
    $StripBom = Join-Path $PSScriptRoot "strip_utf8_bom.py"
    & $Py $StripBom $BackendDir
    if ($LASTEXITCODE -ne 0) { throw "去除 UTF-8 BOM 失败" }

    Write-Host "`[backend`] PyArmor 加密（递归）..."
    $PyarmorArgs = @(
        "-m", "pyarmor.cli", "gen",
        "-r",
        "-O", $ObfDir,
        "start_backend.py",
        "app",
        "secret.py"
    )
    & $Py @PyarmorArgs
    if ($LASTEXITCODE -ne 0) { throw "PyArmor 加密失败" }

    $ObfEntry = Join-Path $ObfDir "start_backend.py"
    if (-not (Test-Path $ObfEntry)) {
        throw "未找到加密后的入口文件: $ObfEntry"
    }

    Write-Host "`[backend`] PyInstaller 打包（onedir）..."
    Push-Location $ObfDir
    try {
        # storage/data 不打入包内：运行时由 app.utils.paths 在 exe 旁（或可写根）创建
        $AddData = @()
        if (Test-Path $FrontendStatic) { $AddData += @("--add-data", "$FrontendStatic;app/static/frontend") }
        if (Test-Path $ConfigJson) { $AddData += @("--add-data", "$ConfigJson;config.json") }
        if (Test-Path $FfmpegBinDir) {
            Write-Host "`[backend`] 打入 FFmpeg 目录: $FfmpegBinDir -> _internal/bin"
            $AddData += @("--add-data", "$FfmpegBinDir;bin")
        } else {
            Write-Host "`[backend`] 警告: 未找到 $FfmpegBinDir ，请放置 ffmpeg.exe/ffprobe.exe 后重打包；否则依赖系统 PATH"
        }

        # MoviePy 依赖 imageio；frozen 环境下若缺少 imageio 的 dist-info，会报
        # "No package metadata was found for imageio"。需 collect + copy-metadata。
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
            "imageio"
            "imageio_ffmpeg"
            "PIL"
            "scenedetect"
            "cryptography"
            "json_repair"
            "faiss"
            "yt_dlp"
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
            "imageio"
            "imageio_ffmpeg"
            "PIL"
            "cryptography"
            "scenedetect"
            "faiss"
            "yt_dlp"
        )

        # PyInstaller：把 pip 包的元数据目录打进包，供 importlib.metadata 查询版本
        $CopyMetadata = @(
            "imageio"
            "imageio-ffmpeg"
            "moviepy"
        )

        $HiddenImports = @(
            "app.main"
            "uvicorn.main"
            "uvicorn.__main__"
            "secret"
            "yt_dlp"
        )

        $ForceCollectArgs = @()
        foreach ($m in $HiddenImports) { $ForceCollectArgs += @("--hidden-import", $m) }
        foreach ($p in $CollectSubmodules) { $ForceCollectArgs += @("--collect-submodules", $p) }
        foreach ($p in $CollectAll) { $ForceCollectArgs += @("--collect-all", $p) }
        foreach ($d in $CopyMetadata) { $ForceCollectArgs += @("--copy-metadata", $d) }

        $IconArgs = @()
        if (Test-Path $LogoIco) {
            Write-Host "`[backend`] 使用 exe 图标: $LogoIco"
            $IconArgs = @("--icon", $LogoIco)
        } else {
            Write-Host "`[backend`] 未找到 $LogoIco ，exe 使用默认图标"
        }

        $PyinstallerArgs = @(
            "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            ("--name=" + $PyinstallerName),
            "--distpath", $PyinstallerDistDir,
            "--workpath", $BuildDir,
            "--specpath", $SpecDir,
            "--collect-submodules", "app",
            "--console",
            "start_backend.py"
        ) + $IconArgs + $ForceCollectArgs + $AddData

        & $Py @PyinstallerArgs
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}

$ProducedDir = Join-Path $PyinstallerDistDir $PyinstallerName
if (-not (Test-Path $ProducedDir)) {
    throw "未找到 PyInstaller 产物目录: $ProducedDir"
}

Write-Host "`[backend`] 导出到 dist/backend ..."
Copy-Item -Path (Join-Path $ProducedDir "*") -Destination $BackendOutDir -Recurse -Force

# 产物重命名为中文可执行文件名（便于用户识别）
$ProducedExe = Join-Path $BackendOutDir ($PyinstallerName + ".exe")
$TargetExe = Join-Path $BackendOutDir ($AppName + ".exe")
if (Test-Path $ProducedExe) {
    Move-Item -Path $ProducedExe -Destination $TargetExe -Force
}

# 将 config.json 放到可执行文件同级目录，便于读写/修改（运行时 secret.get_config 会优先读取此处）
if (Test-Path $ConfigJson) {
    Copy-Item -Path $ConfigJson -Destination (Join-Path $BackendOutDir "config.json") -Force
}

# 生成启动脚本：固定 LX_SMARTCLIP_HOME 到 exe 同目录，避免路径受调用 cwd 影响
$LauncherCmd = @'
@echo off
setlocal
set LX_SMARTCLIP_HOME=%~dp0
"%~dp0lx_smartclip_backend.exe" %*
'@
Set-Content -Path (Join-Path $BackendOutDir "双击我启动.cmd") -Value $LauncherCmd -Encoding UTF8

Write-Host ""
$OutExe = Join-Path $BackendOutDir ($AppName + ".exe")
Write-Host ("Backend build done (PyArmor + PyInstaller): " + $BackendOutDir)
Write-Host ("Executable: " + $OutExe)
Write-Host ""

