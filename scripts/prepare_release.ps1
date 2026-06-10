param(
    [switch]$SkipFrontendBuild,
    [ValidateSet("pyarmor", "nuitka")]
    [string]$Backend = ""
)

$ErrorActionPreference = "Stop"
chcp 65001 > $null

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VersionFile = Join-Path $Root "VERSION"
$ReleaseConfig = Join-Path $Root "release.config.json"

if (-not (Test-Path $VersionFile)) {
    throw "未找到 VERSION 文件: $VersionFile"
}

$Version = (Get-Content $VersionFile -Raw -Encoding UTF8).Trim().Split("`n")[0].Trim()
if (-not $Version) {
    throw "VERSION 文件为空"
}

Write-Host "==> 同步版本号: $Version"

# backend/app/version.json（打包时打入）
$AppVersionJson = Join-Path $Root "backend\app\version.json"
$schemaVersion = 1
$manifest = @{
    app_version     = $Version
    schema_version  = $schemaVersion
    min_schema_version = 1
    breaking        = $false
    requires_backup = $false
}
Write-Utf8NoBom -Path $AppVersionJson -Content ($manifest | ConvertTo-Json -Depth 5 -Compress)

# 复制 release.config.json 到 backend/app（frozen 运行时读取）
if (Test-Path $ReleaseConfig) {
    Copy-Item -Path $ReleaseConfig -Destination (Join-Path $Root "backend\app\release.config.json") -Force
}

# 同步 frontend/package.json version（用 Node 写入，避免 PowerShell BOM/格式问题）
$PkgJsonPath = Join-Path $Root "frontend\package.json"
$SyncScript = Join-Path $PSScriptRoot "sync_package_version.js"
if ((Test-Path $PkgJsonPath) -and (Test-Path $SyncScript)) {
    & node $SyncScript $PkgJsonPath $Version
    if ($LASTEXITCODE -ne 0) { throw "同步 frontend/package.json 版本失败" }
}

Write-Host "==> 开始构建..."
$builder = $Backend
if (-not $builder -and (Test-Path $ReleaseConfig)) {
    try {
        $cfg = Get-Content $ReleaseConfig -Raw -Encoding UTF8 | ConvertFrom-Json
        $builder = [string]$cfg.backend_builder
    } catch {
        # ignore
    }
}
if (-not $builder) { $builder = "nuitka" }
if ($builder -notin @("pyarmor", "nuitka")) { $builder = "nuitka" }
Write-Host "==> 后端打包方案: $builder"
$buildArgs = @($builder)
if ($SkipFrontendBuild) { $buildArgs += "skip-frontend" }
& (Join-Path $PSScriptRoot "build_release.bat") @buildArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

function Resolve-DistBackendRoot {
    param([Parameter(Mandatory = $true)][string]$Root)
    $ExeName = "lx_smartclip_backend.exe"
    $DistDir = Join-Path $Root "dist"
    $Standard = Join-Path $DistDir "backend"

    if (Test-Path (Join-Path $Standard $ExeName)) {
        return $Standard
    }

    $Marker = Join-Path $DistDir ".backend_out"
    if (Test-Path $Marker) {
        $marked = (Get-Content $Marker -Raw -Encoding UTF8).Trim()
        if ($marked -and (Test-Path (Join-Path $marked $ExeName))) {
            return (Resolve-Path $marked).Path
        }
    }

    $fallback = Get-ChildItem -Path $DistDir -Directory -Filter "backend_*" -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName $ExeName) } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($fallback) {
        Write-Host "==> 使用备选后端产物目录: $($fallback.FullName)"
        return $fallback.FullName
    }

    return $Standard
}

$DistBackend = Resolve-DistBackendRoot -Root $Root
if (-not (Test-Path (Join-Path $DistBackend "lx_smartclip_backend.exe"))) {
    throw "Build failed: lx_smartclip_backend.exe not found (checked dist\backend, dist\.backend_out, dist\backend_*)"
}

Write-Host "==> 写入发布元数据..."
Copy-Item -Path $AppVersionJson -Destination (Join-Path $DistBackend "version.json") -Force
if (Test-Path $ReleaseConfig) {
    Copy-Item -Path $ReleaseConfig -Destination (Join-Path $DistBackend "release.config.json") -Force
}

# 升级脚本（从 template 写入 dist，避免 Copy-Item 与杀软误删 .ps1 源文件）
$ToolsDir = Join-Path $DistBackend "tools"
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
$ApplyUpdateTemplate = Join-Path $PSScriptRoot "tools\apply_update.template"
$ApplyUpdateDst = Join-Path $ToolsDir "apply_update.ps1"
if (-not (Test-Path $ApplyUpdateTemplate)) {
    throw "未找到升级脚本模板: $ApplyUpdateTemplate"
}
if (Test-Path $ApplyUpdateDst) {
    attrib -r "$ApplyUpdateDst" /s /d 2>$null
    Remove-Item -Path $ApplyUpdateDst -Force -ErrorAction SilentlyContinue
}
$applyUpdateContent = [System.IO.File]::ReadAllText($ApplyUpdateTemplate)
Write-Utf8NoBom -Path $ApplyUpdateDst -Content $applyUpdateContent

# 示例 data 目录结构（不含用户库）
$dataDir = Join-Path $DistBackend "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "backups") | Out-Null

$ReleaseDir = Join-Path $Root "dist\release"
if (Test-Path $ReleaseDir) { Remove-Item $ReleaseDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

$ZipName = "LX_SmartClip-$Version-win64.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName

Write-Host "==> 打包 zip: $ZipName"
$staging = Join-Path $ReleaseDir "_staging"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

$exclude = @('storage')
Get-ChildItem -Path $DistBackend | ForEach-Object {
    if ($exclude -contains $_.Name) { return }
    if ($_.Name -eq "tools") {
        $stageTools = Join-Path $staging "tools"
        New-Item -ItemType Directory -Force -Path $stageTools | Out-Null
        Copy-Item -Path $ApplyUpdateTemplate -Destination (Join-Path $stageTools "apply_update.template") -Force
        return
    }
    Copy-Item -Path $_.FullName -Destination (Join-Path $staging $_.Name) -Recurse -Force
}

Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $ZipPath -Force
Remove-Item $staging -Recurse -Force

$hash = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$ShaPath = Join-Path $ReleaseDir ($ZipName + ".sha256")
Set-Content -Path $ShaPath -Value "$hash  $ZipName" -Encoding ASCII

$notesPath = Join-Path $ReleaseDir "RELEASE_NOTES.md"
$notesTemplate = @(
    "## LX SmartClip v$Version",
    "",
    "### 升级说明",
    "",
    '```json',
    '{',
    "  `"schema_version`": $schemaVersion,",
    '  "min_schema_version": 1,',
    '  "breaking": false,',
    '  "requires_backup": false',
    '}',
    '```',
    "",
    '> 若本次为**破坏性数据库升级**，请将上面 JSON 中 `breaking` / `requires_backup` 设为 `true`，',
    '> 并填写 `min_schema_version`。用户端升级前会提示先备份。',
    "",
    "### 变更内容",
    "",
    "- （在此填写更新说明）",
    ""
) -join [Environment]::NewLine
Write-Utf8NoBom -Path $notesPath -Content $notesTemplate

$manifestPath = Join-Path $ReleaseDir "release-manifest.json"
Write-Utf8NoBom -Path $manifestPath -Content (($manifestObj = @{
    version = $Version
    tag = "v$Version"
    schema_version = $schemaVersion
    min_schema_version = 1
    breaking = $false
    requires_backup = $false
    assets = @{
        win64 = @{
            file = $ZipName
            sha256 = $hash
            size = (Get-Item $ZipPath).Length
        }
    }
}) | ConvertTo-Json -Depth 6)

Write-Host ""
Write-Host "========================================"
Write-Host "  发布包已就绪"
Write-Host "========================================"
Write-Host "  版本:     $Version"
Write-Host "  ZIP:      $ZipPath"
Write-Host "  SHA256:   $ShaPath"
Write-Host "  说明模板: $notesPath"
Write-Host ""
Write-Host "下一步（任选其一）："
Write-Host "  1) 自动发布到 GitHub 公开发版仓:"
Write-Host "       scripts\publish_release.bat"
Write-Host "  2) 手动发布:"
Write-Host "       - 编辑 $notesPath"
Write-Host "       - 在 GitHub 公开发版仓创建 Release v$Version"
Write-Host "       - 上传 $ZipName 与 $($ZipName).sha256"
Write-Host "========================================"
