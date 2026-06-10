# 为发布打包准备仓库根目录 ffmpeg\bin（ffmpeg.exe / ffprobe.exe）
# 若已存在则跳过；否则从 gyan.dev essentials 构建下载

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # ignore
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FfmpegBinDir = Join-Path $Root "ffmpeg\bin"
$FfmpegExe = Join-Path $FfmpegBinDir "ffmpeg.exe"
$FfprobeExe = Join-Path $FfmpegBinDir "ffprobe.exe"

function Ensure-FfmpegBinaries {
    if ((Test-Path $FfmpegExe) -and (Test-Path $FfprobeExe)) {
        Write-Host "[ffmpeg] 已存在: $FfmpegBinDir"
        return
    }

    Write-Host "[ffmpeg] 未找到本地二进制，正在下载 Windows essentials 构建..."
    $ZipUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    $TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("lx_smartclip_ffmpeg_" + [Guid]::NewGuid().ToString("N"))
    $ZipPath = Join-Path $TempRoot "ffmpeg.zip"
    $ExtractDir = Join-Path $TempRoot "extract"

    New-Item -Path $TempRoot -ItemType Directory -Force | Out-Null
    New-Item -Path $ExtractDir -ItemType Directory -Force | Out-Null
    New-Item -Path $FfmpegBinDir -ItemType Directory -Force | Out-Null

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath -UseBasicParsing
        Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force

        $FoundFfmpeg = Get-ChildItem -Path $ExtractDir -Recurse -Filter "ffmpeg.exe" -File -ErrorAction SilentlyContinue |
            Select-Object -First 1
        $FoundFfprobe = Get-ChildItem -Path $ExtractDir -Recurse -Filter "ffprobe.exe" -File -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if (-not $FoundFfmpeg -or -not $FoundFfprobe) {
            throw "下载包中未找到 ffmpeg.exe 或 ffprobe.exe"
        }

        Copy-Item -Path $FoundFfmpeg.FullName -Destination $FfmpegExe -Force
        Copy-Item -Path $FoundFfprobe.FullName -Destination $FfprobeExe -Force
        Write-Host "[ffmpeg] 已写入: $FfmpegExe"
        Write-Host "[ffmpeg] 已写入: $FfprobeExe"
    } finally {
        if (Test-Path $TempRoot) {
            Remove-Item -Path $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Ensure-FfmpegBinaries

if (-not (Test-Path $FfmpegExe) -or -not (Test-Path $FfprobeExe)) {
    throw "FFmpeg 准备失败：请手动将 ffmpeg.exe/ffprobe.exe 放入 $FfmpegBinDir"
}
