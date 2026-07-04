param(
    [Parameter(Mandatory = $true)][string]$BackendOutDir
)

$LauncherCmd = @'
@echo off
setlocal
set "LX_SMARTCLIP_HOME=%~dp0"
REM bundled FFmpeg: PyInstaller -> _internal\bin, Nuitka -> bin
if exist "%~dp0_internal\bin\ffmpeg.exe" (
  set "PATH=%~dp0_internal\bin;%PATH%"
  set "FFMPEG_BIN=%~dp0_internal\bin\ffmpeg.exe"
  set "FFPROBE_BIN=%~dp0_internal\bin\ffprobe.exe"
  set "IMAGEIO_FFMPEG_EXE=%~dp0_internal\bin\ffmpeg.exe"
) else if exist "%~dp0bin\ffmpeg.exe" (
  set "PATH=%~dp0bin;%PATH%"
  set "FFMPEG_BIN=%~dp0bin\ffmpeg.exe"
  set "FFPROBE_BIN=%~dp0bin\ffprobe.exe"
  set "IMAGEIO_FFMPEG_EXE=%~dp0bin\ffmpeg.exe"
)
REM bundled Playwright Chromium (publisher fallback; local Chrome/Edge preferred at runtime)
if exist "%~dp0_internal\ms-playwright\." (
  set "PLAYWRIGHT_BROWSERS_PATH=%~dp0_internal\ms-playwright"
) else if exist "%~dp0ms-playwright\." (
  set "PLAYWRIGHT_BROWSERS_PATH=%~dp0ms-playwright"
)
"%~dp0lx_smartclip_backend.exe" %*
'@

# Avoid non-ASCII literals in source (PS 5.1 may misread UTF-8 without BOM)
$LauncherName = [string][char]0x53CC + [char]0x51FB + [char]0x6211 + [char]0x542F + [char]0x52A8 + ".cmd"
$LauncherPath = Join-Path $BackendOutDir $LauncherName
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($LauncherPath, $LauncherCmd, $Utf8NoBom)
