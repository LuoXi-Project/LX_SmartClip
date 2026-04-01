$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendDir = Join-Path $Root "frontend"
$FrontendOut = Join-Path $FrontendDir "out"
$BackendWebDir = Join-Path $Root "backend\app\static\frontend"
$DistDir = Join-Path $Root "dist"

Write-Host "[1/5] 检查目录..."
if (-not (Test-Path (Join-Path $FrontendDir "package.json"))) {
    throw "未找到前端目录或 package.json: $FrontendDir"
}

Write-Host "[2/5] 安装前端依赖..."
Push-Location $FrontendDir
try {
    npm install
    if ($LASTEXITCODE -ne 0) {
        throw "npm install 失败"
    }

    Write-Host "[3/5] 构建前端导出产物..."
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "npm run build 失败"
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $FrontendOut "index.html"))) {
    throw "未找到导出产物: $FrontendOut\index.html"
}

Write-Host "[4/5] 拷贝构建产物到后端静态目录..."
if (Test-Path $BackendWebDir) {
    Remove-Item -Path $BackendWebDir -Recurse -Force
}
New-Item -Path $BackendWebDir -ItemType Directory -Force | Out-Null
Copy-Item -Path (Join-Path $FrontendOut "*") -Destination $BackendWebDir -Recurse -Force

Write-Host "[5/5] Nuitka 构建后端并导出 dist/..."
if (-not (Test-Path $DistDir)) {
    New-Item -Path $DistDir -ItemType Directory -Force | Out-Null
}
& (Join-Path $PSScriptRoot "build_backend_nuitka.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "后端 Nuitka 构建失败"
}

Write-Host ""
Write-Host "打包完成："
Write-Host "前端产物: $FrontendOut"
Write-Host "后端挂载目录: $BackendWebDir"
Write-Host "发布目录: $DistDir"
Write-Host ""
Write-Host "提示：发布版本请使用 dist/backend/lx_smartclip_backend.exe 启动（会自动找空闲端口）。"
