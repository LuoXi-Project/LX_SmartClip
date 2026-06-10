param(
    [string]$HostIP = "127.0.0.1"
)

chcp 65001 > $null

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # ignore
}

function Invoke-NativeExe {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [object[]]$ArgumentList = @()
    )
    # pyarmor/pip/PyInstaller 等常把正常输出写到 stderr；Stop 模式下勿将其视为终止错误
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($ArgumentList.Count -gt 0) {
            & $Exe @ArgumentList
        } else {
            & $Exe
        }
    } finally {
        $ErrorActionPreference = $prevEap
    }
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
$PyarmorVersion = "7.7.4"
$CollectObfScript = Join-Path $PSScriptRoot "collect_obf_hidden_imports.py"
$ValidateScript = Join-Path $PSScriptRoot "validate_obf_bundle.py"

$VenvPythonCandidates = @(
    (Join-Path $Root "venv-py310\\Scripts\\python.exe"),
    (Join-Path $Root "venv-py310\\python.exe"),
    (Join-Path $Root "venv\\Scripts\\python.exe"),
    (Join-Path $Root "venv\\python.exe"),
    (Join-Path $BackendDir "venv\\Scripts\\python.exe")
)
$Py = ($VenvPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Py) { $Py = "python" }

function Test-Py310OrLower {
    param([string]$PythonExe)
    try {
        $minor = & $PythonExe -c "import sys; print(sys.version_info.minor)" 2>$null
        $major = & $PythonExe -c "import sys; print(sys.version_info.major)" 2>$null
        return ([int]$major -eq 3 -and [int]$minor -le 10)
    } catch {
        return $false
    }
}

if (-not (Test-Py310OrLower $Py)) {
    $fallbacks = @(
        $env:LX_RELEASE_PYTHON,
        $env:LX_PYARMOR_PYTHON,
        (Join-Path $Root "venv-py310\\Scripts\\python.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }
    foreach ($candidate in $fallbacks) {
        if (Test-Py310OrLower $candidate) {
            $Py = $candidate
            break
        }
    }
    try {
        $py310 = (& py -3.10 -c "import sys; print(sys.executable)" 2>$null).Trim()
        if ($py310 -and (Test-Path $py310) -and (Test-Py310OrLower $py310)) { $Py = $py310 }
    } catch { }
}

if (-not (Test-Py310OrLower $Py)) {
    $cur = try { (& $Py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim() } catch { "unknown" }
    throw @"
PyArmor 7 仅支持 Python 3.7–3.10，当前为 Python $cur。

请先运行（需本机已安装 Python 3.10）：
  scripts\setup_release_py310.bat

或设置环境变量 LX_RELEASE_PYTHON 指向 Python 3.10 解释器。
"@
}

Write-Host "`[backend`] 打包 Python: $Py"

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
    $PyarmorOk = $false
    try {
        $verLine = & $Py -c "import pyarmor; print(getattr(pyarmor, '__version__', ''))" 2>$null
        if ($verLine -match '^7\.') { $PyarmorOk = $true }
    } catch {
        $PyarmorOk = $false
    }
    if (-not $PyarmorOk) {
        Write-Host "`[backend`] 安装 PyArmor $PyarmorVersion（7.x 免费版，替换 8/9 如有）..."
        & $Py -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip 升级失败" }
        # pip 对未安装包会写 WARNING 到 stderr；Stop 模式下 PowerShell 会将其视为终止错误
        Invoke-NativeExe $Py @("-m", "pip", "uninstall", "-y", "pyarmor", "pyarmor.cli.core") *> $null
        & $Py -m pip install "pyarmor==$PyarmorVersion"
        if ($LASTEXITCODE -ne 0) { throw "PyArmor 安装失败" }
    }

    $PyarmorExe = Join-Path (Split-Path $Py -Parent) "pyarmor.exe"
    if (-not (Test-Path $PyarmorExe)) {
        $PyarmorExe = Join-Path $Root "venv\Scripts\pyarmor.exe"
    }
    if (-not (Test-Path $PyarmorExe)) {
        $PyarmorExe = Join-Path $Root "venv\pyarmor.exe"
    }
    if (-not (Test-Path $PyarmorExe)) {
        throw "未找到 pyarmor.exe，请确认 venv 中已安装 pyarmor==$PyarmorVersion"
    }
    $PyarmorVerOut = (Invoke-NativeExe $PyarmorExe @("--version") 2>&1 | Out-String).Trim()
    Write-Host "`[backend`] PyArmor 版本: $PyarmorVerOut"

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

    Write-Host "`[backend`] PyArmor 7 加密（递归，--package-runtime 1 生成 pytransform 供 PyInstaller 打入）..."
    # 打包不变量（由 validate_obf_bundle.py 在构建期强制检查）：
    # 1. 仅 start_backend.py 作为 PyArmor 入口；其余模块只走 --recursive，禁止多入口
    # 2. --add-data 禁止写入 bundle/app/（会 shadow Python 包 app）
    # 3. hidden-import 从 obf/ 全量扫描（collect_submodules 对混淆代码无效）
    # 4. _pytransform.dll 需同时存在于 _internal/ 与 _internal/pytransform/
    if (Test-Path $ObfDir) {
        Remove-PathForce -PathToRemove $ObfDir
    }
    New-Item -Path $ObfDir -ItemType Directory -Force | Out-Null
    $PyarmorArgs = @(
        "obfuscate",
        "--recursive",
        "--output", $ObfDir,
        "--package-runtime", "1",
        "--exclude", "__pycache__",
        "start_backend.py"
    )
    # secret.py 勿作为 PyArmor 入口：作为入口会在模块顶层注入 protect_pytransform，
    # import secret 时重复执行且 secret.py 无 import sys，导致 NameError。
    Invoke-NativeExe $PyarmorExe $PyarmorArgs
    if ($LASTEXITCODE -ne 0) { throw "PyArmor 加密失败" }

    $ObfEntry = Join-Path $ObfDir "start_backend.py"
    if (-not (Test-Path $ObfEntry)) {
        throw "未找到加密后的入口文件: $ObfEntry"
    }
    $PytransformDir = Join-Path $ObfDir "pytransform"
    if (-not (Test-Path $PytransformDir)) {
        Write-Host "`[backend`] 未在 obf 根目录找到 pytransform，尝试 pyarmor runtime 单独生成..."
        Invoke-NativeExe $PyarmorExe @("runtime", "-O", $ObfDir)
        if ($LASTEXITCODE -ne 0) { throw "PyArmor runtime 生成失败" }
    }
    if (-not (Test-Path $PytransformDir)) {
        throw "未找到 PyArmor 7 运行时目录 pytransform/: $PytransformDir"
    }

    if (Test-Path $ValidateScript) {
        Write-Host "`[backend`] 校验 obf 产物（单入口保护 / 包结构）..."
        & $Py $ValidateScript --obf-dir $ObfDir --skip-exe
        if ($LASTEXITCODE -ne 0) { throw "obf 校验失败，请检查 PyArmor 入口脚本配置" }
    }

    Write-Host "`[backend`] PyInstaller 打包（onedir）..."
    Push-Location $ObfDir
    try {
        # storage/data 不打入包内：运行时由 app.utils.paths 在 exe 旁（或可写根）创建
        # 规则：禁止 --add-data 写入 bundle 下的 app/ 目录（会 shadow Python 包 app，导致 import app.* 失败）
        $AddData = @()
        if (Test-Path $FrontendStatic) { $AddData += @("--add-data", "$FrontendStatic;static/frontend") }
        if (Test-Path $ConfigJson) { $AddData += @("--add-data", "$ConfigJson;config.json") }
        $AppVersionJson = Join-Path $BackendDir "app\version.json"
        if (Test-Path $AppVersionJson) {
            # 勿写入 bundle/app/，否则会 shadow Python 包 app，导致 import app.utils 失败
            $AddData += @("--add-data", "$AppVersionJson;.")
        }
        $AppReleaseConfig = Join-Path $BackendDir "app\release.config.json"
        if (Test-Path $AppReleaseConfig) {
            $AddData += @("--add-data", "$AppReleaseConfig;.")
        }
        if (Test-Path $FfmpegBinDir) {
            Write-Host "`[backend`] 打入 FFmpeg 目录: $FfmpegBinDir -> _internal/bin"
            $AddData += @("--add-data", "$FfmpegBinDir;bin")
        } else {
            Write-Host "`[backend`] 警告: 未找到 $FfmpegBinDir ，请放置 ffmpeg.exe/ffprobe.exe 后重打包；否则依赖系统 PATH"
        }
        if (Test-Path $PytransformDir) {
            $AddData += @("--add-data", "$PytransformDir;pytransform")
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
            "pyJianYingDraft"
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
            "pyJianYingDraft"
        )

        # PyInstaller：把 pip 包的元数据目录打进包，供 importlib.metadata 查询版本
        $CopyMetadata = @(
            "imageio"
            "imageio-ffmpeg"
            "moviepy"
        )

        # PyArmor 混淆后 Analysis 阶段无法正常 import app.*，collect_submodules 会漏掉大量子包。
        # 从 obf/ 目录扫描全部 .py，生成完整 --hidden-import 列表（一次性解决 app.db / app.api 等缺失）。
        $ObfHiddenImports = @()
        if (Test-Path $CollectObfScript) {
            $ObfHiddenImports = @(& $Py $CollectObfScript $ObfDir 2>$null | Where-Object { $_ -and $_.Trim() })
            Write-Host ("`[backend`] obf hidden-import 模块数: " + $ObfHiddenImports.Count)
        } else {
            Write-Host "`[backend`] 警告: 未找到 $CollectObfScript，PyInstaller 可能漏打 app 子模块"
        }

        $HiddenImports = @(
            "pytransform"
            "uvicorn.main"
            "uvicorn.__main__"
            "yt_dlp"
            "pyJianYingDraft"
            "pyJianYingDraft.time_util"
        ) + $ObfHiddenImports

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
            "--paths", $ObfDir,
            "--collect-submodules", "app",
            "--console",
            "start_backend.py"
        ) + $IconArgs + $ForceCollectArgs + $AddData

        Invoke-NativeExe $Py $PyinstallerArgs
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

# PyArmor --package-runtime 1 的保护代码在 frozen 下于 _internal 根目录校验 _pytransform.dll，
# 而 PyInstaller --add-data 将其放在 _internal/pytransform/ 下，需额外复制一份到根目录。
$InternalDir = Join-Path $BackendOutDir "_internal"
$PytransformDll = Join-Path $InternalDir "pytransform\_pytransform.dll"
$PytransformDllRoot = Join-Path $InternalDir "_pytransform.dll"
if (Test-Path $PytransformDll) {
    Copy-Item -Path $PytransformDll -Destination $PytransformDllRoot -Force
    Write-Host "`[backend`] 已复制 _pytransform.dll 到 _internal 根目录（PyArmor runtime 校验路径）"
} else {
    Write-Host "`[backend`] 警告: 未找到 _internal/pytransform/_pytransform.dll，运行时可能报 PyArmor 错误"
}

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

# dist\backend 被占用时会写入 backend_<时间戳>；尽量归并并留下标记供 prepare_release 解析
$StandardBackend = Join-Path $DistDir "backend"
if ($BackendOutDir -ne $StandardBackend) {
    Write-Host "`[backend`] 产物在备选目录: $BackendOutDir"
    Write-Host "`[backend`] 尝试归并到 dist\backend ..."
    try {
        if (Test-Path $StandardBackend) {
            $leftover = @(Get-ChildItem -Path $StandardBackend -Force | Where-Object { $_.Name -notin '.', '..' })
            if ($leftover.Count -eq 0) {
                Remove-PathForce -PathToRemove $StandardBackend
            }
        }
        if (-not (Test-Path $StandardBackend)) {
            Move-Item -Path $BackendOutDir -Destination $StandardBackend -Force
            $BackendOutDir = $StandardBackend
            Write-Host "`[backend`] 已归并到 dist\backend"
        } else {
            Write-Host "`[backend`] 警告: dist\backend 仍被占用或非空，产物保留在 $BackendOutDir"
        }
    } catch {
        Write-Host "`[backend`] 警告: 无法归并到 dist\backend: $($_.Exception.Message)"
    }
}
$MarkerPath = Join-Path $DistDir ".backend_out"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($MarkerPath, $BackendOutDir, $utf8NoBom)

Write-Host ""
$OutExe = Join-Path $BackendOutDir ($AppName + ".exe")

if (Test-Path $ValidateScript) {
    Write-Host "`[backend`] 冻结包冒烟测试（--validate-frozen）..."
    & $OutExe --validate-frozen
    if ($LASTEXITCODE -ne 0) {
        throw "冻结包冒烟测试失败：关键模块 import 未通过，请查看上方错误"
    }
}

Write-Host ("Backend build done (PyArmor 7 + PyInstaller): " + $BackendOutDir)
Write-Host ("Executable: " + $OutExe)
Write-Host ""

