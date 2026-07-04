# 准备 Playwright Chromium 浏览器引擎（用于一键发布功能）
# 仿 prepare_ffmpeg.ps1 范式：用 venv python 跑 playwright install，确保浏览器修订版本与 pip 包匹配
# 产物落 <repo_root>/playwright/ms-playwright/，构建时由 --add-data 打入 _internal/ms-playwright
$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # ignore
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# 目标目录：<repo_root>\playwright\ms-playwright\
$TargetRoot = Join-Path $Root "playwright\ms-playwright"
Write-Host "[playwright] 目标目录: $TargetRoot"

# 定位 venv python（与 build_backend_pyarmor_pyinstaller.ps1 一致）
$VenvPythonCandidates = @(
    (Join-Path $Root "venv\Scripts\python.exe"),
    (Join-Path $Root "backend\venv\Scripts\python.exe")
)
$Py = ($VenvPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Py) { $Py = "python" }
Write-Host "[playwright] 使用 Python: $Py"

# 确保 patchright 已安装（playwright install 命令由 playwright/patchright 包提供）
& $Py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('patchright') else 1)" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[playwright] 未检测到 patchright，安装中..."
    & $Py -m pip install --upgrade patchright
    if ($LASTEXITCODE -ne 0) { throw "patchright 安装失败" }
}

# 通过 PLAYWRIGHT_BROWSERS_PATH 控制 playwright install 的下载位置，
# 直接装到目标目录（避免后续从 %USERPROFILE% 复制）
$env:PLAYWRIGHT_BROWSERS_PATH = $TargetRoot

# 幂等：若目标目录已有 chromium-* 且含 chrome.exe，则跳过（兼容新旧目录结构）
$ExistingChromium = Get-ChildItem -Path $TargetRoot -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($ExistingChromium) {
    $ChromeExe = Join-Path $ExistingChromium.FullName "chrome-win64\chrome.exe"
    if (-not (Test-Path $ChromeExe)) {
        $ChromeExe = Join-Path $ExistingChromium.FullName "chrome-win\chrome.exe"
    }
    if (Test-Path $ChromeExe) {
        Write-Host "[playwright] 已存在 Chromium: $($ExistingChromium.Name)，跳过下载"
        return
    }
}

# 创建目标目录
if (-not (Test-Path $TargetRoot)) {
    New-Item -Path $TargetRoot -ItemType Directory -Force | Out-Null
}

# 下载 Chromium（用 patchright 的 install 命令，版本天然匹配 pip 包）
Write-Host "[playwright] 下载 Chromium 浏览器引擎（约 170MB）..."
& $Py -m patchright install chromium
if ($LASTEXITCODE -ne 0) {
    # 退回用 playwright install（兼容旧版）
    Write-Host "[playwright] patchright install 失败，尝试 playwright install..."
    & $Py -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "Chromium 下载失败" }
}

# 校验产物
Write-Host "[playwright] 校验下载产物..."
& $Py (Join-Path $PSScriptRoot "check_playwright_deps.py") $TargetRoot
if ($LASTEXITCODE -ne 0) {
    throw "Playwright Chromium 校验失败，请检查网络或手动执行: `$env:PLAYWRIGHT_BROWSERS_PATH='$TargetRoot'; python -m patchright install chromium"
}

Write-Host "[playwright] Chromium 准备完成: $TargetRoot"
