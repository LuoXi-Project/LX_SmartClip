# 准备动效渲染（HyperFrames）运行时：Node.js + 渲染依赖
# 仿 prepare_playwright.ps1 范式：
#   - Node LTS 便携版 node.exe → <repo_root>\node\node.exe（打包时 --add-data 进 _internal/bin）
#   - 渲染依赖 node_modules → <repo_root>\motion-runtime\node_modules（打包时整体打入 _internal/motion-runtime/node_modules）
# 均幂等：已存在则跳过。运行时由 backend/app/core/motion/runtime.py 自动解析。
$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # ignore
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# 与 backend/app/core/motion/bridge/package.json 的依赖清单保持同步（实测通过的版本）
$NodeVersion = "v22.14.0"
$NodeZipUrl = "https://nodejs.org/dist/$NodeVersion/node-$NodeVersion-win-x64.zip"
$ProducerVersion = "0.9.52"

# ── 1) Node.js 便携版 ────────────────────────────────────────────────────────
$NodeTarget = Join-Path $Root "node\node.exe"
if (Test-Path $NodeTarget) {
    Write-Host "[motion] 已存在 Node: $NodeTarget，跳过下载"
} else {
    $ZipPath = Join-Path $env:TEMP "node-$NodeVersion-win-x64.zip"
    Write-Host "[motion] 下载 Node $NodeVersion（约 30MB）..."
    Invoke-WebRequest -Uri $NodeZipUrl -OutFile $ZipPath -UseBasicParsing
    $ExtractDir = Join-Path $env:TEMP "node-$NodeVersion-win-x64"
    if (Test-Path $ExtractDir) { Remove-Item $ExtractDir -Recurse -Force }
    Expand-Archive -Path $ZipPath -DestinationPath $env:TEMP -Force
    New-Item -Path (Join-Path $Root "node") -ItemType Directory -Force | Out-Null
    Copy-Item (Join-Path $ExtractDir "node.exe") $NodeTarget -Force
    Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
    Remove-Item $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[motion] Node 就绪: $NodeTarget"
}

# ── 2) 渲染依赖 node_modules ────────────────────────────────────────────────
$MotionRoot = Join-Path $Root "motion-runtime"
$ProducerPkg = Join-Path $MotionRoot "node_modules\@hyperframes\producer"
if (Test-Path $ProducerPkg) {
    Write-Host "[motion] 已存在渲染依赖: $ProducerPkg，跳过安装"
} else {
    New-Item -Path $MotionRoot -ItemType Directory -Force | Out-Null
    # 用仓库内 bridge/package.json（版本单一事实源），不是手写清单
    Copy-Item (Join-Path $Root "backend\app\core\motion\bridge\package.json") (Join-Path $MotionRoot "package.json") -Force
    $env:PUPPETEER_SKIP_DOWNLOAD = "1"
    $env:PUPPETEER_SKIP_CHROMIUM_DOWNLOAD = "1"
    Write-Host "[motion] npm install 渲染依赖（@hyperframes/producer $ProducerVersion，约 1~2 分钟）..."
    Push-Location $MotionRoot
    try {
        # 优先用刚准备的便携 Node；PATH 保证 npm/npx 可用
        $env:PATH = "$Root\node;$env:PATH"
        npm install --omit=dev --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) { throw "渲染依赖 npm install 失败" }
    }
    finally {
        Pop-Location
        Remove-Item env:PUPPETEER_SKIP_DOWNLOAD -ErrorAction SilentlyContinue
        Remove-Item env:PUPPETEER_SKIP_CHROMIUM_DOWNLOAD -ErrorAction SilentlyContinue
    }
}

# ── 3) 校验 ─────────────────────────────────────────────────────────────────
if (-not (Test-Path $NodeTarget)) { throw "Node 未就绪: $NodeTarget" }
$ProducerEntry = Join-Path $ProducerPkg "dist\index.js"
if (-not (Test-Path $ProducerEntry)) { throw "producer 入口缺失: $ProducerEntry" }
if (-not (Test-Path (Join-Path $MotionRoot "node_modules\@hyperframes\core\dist\hyperframe.runtime.iife.js"))) {
    throw "@hyperframes/core runtime IIFE 缺失（预览注入需要）"
}

Write-Host "[motion] 动效渲染运行时准备完成: $MotionRoot"
