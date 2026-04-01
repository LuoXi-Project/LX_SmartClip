param(
    [string]$HostIP = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

# 避免中文输出在某些终端/重定向场景下出现乱码
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
            # 先尝试清只读属性，降低 Remove-Item 失败概率
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
$NuitkaOutBaseDir = Join-Path $DistDir "_nuitka"
$NuitkaOutDir = $NuitkaOutBaseDir
$BackendOutDir = Join-Path $DistDir "backend"
$VenvPythonCandidates = @(
    (Join-Path $Root "venv\Scripts\python.exe"),
    (Join-Path $BackendDir "venv\Scripts\python.exe")
)
$Py = ($VenvPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Py) { $Py = "python" }

Write-Host "[backend] 检查入口文件..."
if (-not (Test-Path $Entry)) {
    throw "未找到后端入口: $Entry"
}

Write-Host "[backend] 清理 dist/backend ..."
if (Test-Path $BackendOutDir) {
    Remove-PathForce -PathToRemove $BackendOutDir
}
New-Item -Path $BackendOutDir -ItemType Directory -Force | Out-Null

Write-Host "[backend] 准备 Nuitka 输出目录..."
if (Test-Path $NuitkaOutDir) {
    try {
        Remove-PathForce -PathToRemove $NuitkaOutDir
    } catch {
        # 如果旧输出目录里有文件被占用，无法删除，则切换到全新目录继续构建
        $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $NuitkaOutDir = Join-Path $DistDir ("_nuitka_" + $Stamp)
        Write-Host "[backend] 注意：旧的 _nuitka 无法清理（文件占用），改用新目录：$NuitkaOutDir"
    }
}
New-Item -Path $NuitkaOutDir -ItemType Directory -Force | Out-Null

# 额外清理：Nuitka 有时会在 output-dir 里残留 *.build/*.dist，残留会导致断言“文件已存在”
Get-ChildItem -Path $DistDir -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*.build" -or $_.Name -like "*.dist" } |
    ForEach-Object { Remove-PathForce -PathToRemove $_.FullName }

# 需要把前端静态资源/存储目录/数据目录一并带到可分发目录中（供后端挂载/生成 DB）
$FrontendStatic = Join-Path $BackendDir "app\static\frontend"
$StorageDir = Join-Path $BackendDir "storage"
$DataDir = Join-Path $BackendDir "data"

Write-Host "[backend] 运行 Nuitka（standalone）..."
Push-Location $BackendDir
try {
    Write-Host "[backend] 检查 Nuitka 依赖..."
    & $Py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('nuitka') else 1)" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[backend] 未检测到 Nuitka，正在安装..."
        & $Py -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip 升级失败" }
        & $Py -m pip install --upgrade Nuitka
        if ($LASTEXITCODE -ne 0) { throw "Nuitka 安装失败" }
    }

    # 精准清理本次入口对应的 build/dist 目录，避免断言“文件已存在”
    $BuildDir = Join-Path $NuitkaOutDir "start_backend.build"
    $ThisDistDir = Join-Path $NuitkaOutDir "start_backend.dist"
    if (Test-Path $BuildDir) { Remove-PathForce -PathToRemove $BuildDir }
    if (Test-Path $ThisDistDir) { Remove-PathForce -PathToRemove $ThisDistDir }

    $Args = @(
        "-m", "nuitka",
        "--standalone",
        "--follow-imports",
        "--show-progress",
        "--show-scons",
        # Avoid compiling extremely large 3rd-party deps; they are still copied into standalone dist.
        "--nofollow-import-to=torch,numpy,cv2,faiss,whisper,scenedetect",
        "--include-module=app.main",
        "--assume-yes-for-downloads",
        "--output-dir=$NuitkaOutDir",
        "--output-filename=lx_smartclip_backend",
        "--windows-console-mode=force",
        "--include-data-dir=$FrontendStatic=app/static/frontend",
        "--include-data-dir=$StorageDir=storage",
        "--include-data-dir=$DataDir=data",
        $Entry
    )

    & $Py @Args
    if ($LASTEXITCODE -ne 0) { throw "Nuitka 构建失败" }
}
finally {
    Pop-Location
}

$ProducedDist = Join-Path $NuitkaOutDir "start_backend.dist"
if (-not (Test-Path $ProducedDist)) {
    throw "未找到 Nuitka 产物目录: $ProducedDist"
}

Write-Host "[backend] 导出到 dist/backend ..."
Copy-Item -Path (Join-Path $ProducedDist "*") -Destination $BackendOutDir -Recurse -Force

Write-Host ""
Write-Host "后端构建完成：$BackendOutDir"
Write-Host "可执行文件：$(Join-Path $BackendOutDir 'lx_smartclip_backend.exe')"
Write-Host ""

