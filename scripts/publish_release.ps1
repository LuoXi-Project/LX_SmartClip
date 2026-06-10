param(
    [switch]$Draft,
    [string]$NotesFile = ""
)

$ErrorActionPreference = "Stop"
chcp 65001 > $null

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VersionFile = Join-Path $Root "VERSION"
$ReleaseConfigPath = Join-Path $Root "release.config.json"
$ReleaseDir = Join-Path $Root "dist\release"

if (-not (Test-Path $VersionFile)) { throw "未找到 VERSION" }
$Version = (Get-Content $VersionFile -Raw -Encoding UTF8).Trim().Split("`n")[0].Trim()
$Tag = "v$Version"
$ZipName = "LX_SmartClip-$Version-win64.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName
$ShaPath = Join-Path $ReleaseDir ($ZipName + ".sha256")
$DefaultNotes = Join-Path $ReleaseDir "RELEASE_NOTES.md"

if (-not (Test-Path $ZipPath)) {
    Write-Host "未找到发布包，先运行: scripts\prepare_release.bat" -ForegroundColor Yellow
    exit 1
}

$config = @{}
if (Test-Path $ReleaseConfigPath) {
    $config = Get-Content $ReleaseConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
$ReleaseRepo = [string]$config.release_repo
if (-not $ReleaseRepo) {
    Write-Host ""
    Write-Host "请在 release.config.json 中设置 release_repo，例如:" -ForegroundColor Yellow
    Write-Host '  "release_repo": "YourOrg/LX_SmartClip-Releases"' -ForegroundColor Cyan
    exit 1
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Host ""
    Write-Host "未安装 GitHub CLI (gh)。可手动发布：" -ForegroundColor Yellow
    Write-Host "  1. 打开 https://github.com/$ReleaseRepo/releases/new?tag=$Tag"
    Write-Host "  2. 上传: $ZipPath"
    Write-Host "  3. 上传: $ShaPath"
    Write-Host "  4. 正文粘贴: $DefaultNotes"
    exit 0
}

$authStatus = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "请先登录 GitHub CLI: gh auth login" -ForegroundColor Yellow
    exit 1
}

$notesPath = $NotesFile
if (-not $notesPath) { $notesPath = $DefaultNotes }
if (-not (Test-Path $notesPath)) {
    throw "未找到 Release 说明: $notesPath"
}
$notes = Get-Content $notesPath -Raw -Encoding UTF8

Write-Host ""
Write-Host "即将发布到: https://github.com/$ReleaseRepo/releases/tag/$Tag"
Write-Host "  ZIP: $ZipPath"
Write-Host ""
$confirm = Read-Host "确认发布? [y/N]"
if ($confirm -notmatch '^[yY]') {
    Write-Host "已取消"
    exit 0
}

$args = @(
    "release", "create", $Tag,
    "--repo", $ReleaseRepo,
    "--title", "LX SmartClip $Tag",
    "--notes-file", $notesPath,
    $ZipPath
)
if (Test-Path $ShaPath) { $args += $ShaPath }
if ($Draft) { $args += "--draft" }

& gh @args
if ($LASTEXITCODE -ne 0) {
    Write-Host "发布失败。若 tag 已存在，可先删除或使用新版本号。" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "发布成功: https://github.com/$ReleaseRepo/releases/tag/$Tag" -ForegroundColor Green
Write-Host ""
Write-Host "提示："
Write-Host "  - 私密源码仓无需公开；用户端通过 release.config.json 中的 release_repo 检查更新"
Write-Host "  - 破坏性升级时，请编辑 RELEASE_NOTES.md 顶部 JSON，设置 requires_backup: true"
