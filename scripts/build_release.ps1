$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendDir = Join-Path $Root "frontend"
$FrontendOut = Join-Path $FrontendDir "out"
$BackendWebDir = Join-Path $Root "backend\app\static\frontend"

Write-Host "[1/4] 检查目录..."
if (-not (Test-Path (Join-Path $FrontendDir "package.json"))) {
    throw "未找到前端目录或 package.json: $FrontendDir"
}

Write-Host "[2/4] 安装前端依赖..."
Push-Location $FrontendDir
try {
    npm install
    if ($LASTEXITCODE -ne 0) {
        throw "npm install 失败"
    }

    Write-Host "[3/4] 构建前端导出产物..."
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

Write-Host "[4/4] 拷贝构建产物到后端静态目录..."
if (Test-Path $BackendWebDir) {
    Remove-Item -Path $BackendWebDir -Recurse -Force
}
New-Item -Path $BackendWebDir -ItemType Directory -Force | Out-Null
Copy-Item -Path (Join-Path $FrontendOut "*") -Destination $BackendWebDir -Recurse -Force

Write-Host ""
Write-Host "打包完成："
Write-Host "前端产物: $FrontendOut"
Write-Host "后端挂载目录: $BackendWebDir"
Write-Host ""
Write-Host "现在启动后端后，直接访问 http://127.0.0.1:8000 即可同域访问前后端。"
