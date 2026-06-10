param(
    [switch]$Force,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
chcp 65001 > $null

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvDir = Join-Path $Root "venv"
$ReqFile = Join-Path $Root "backend\requirements.txt"

function Find-Conda {
    if ($env:CONDA_EXE -and (Test-Path $env:CONDA_EXE)) { return $env:CONDA_EXE }
    $candidates = @(
        "D:\Miniconda3\Scripts\conda.exe",
        "C:\Miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\Miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe"
    )
    return ($candidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
}

function Test-Py310 {
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path $Exe)) { return $false }
    try {
        $minor = [int](& $Exe -c "import sys; print(sys.version_info.minor)" 2>$null)
        $major = [int](& $Exe -c "import sys; print(sys.version_info.major)" 2>$null)
        return ($major -eq 3 -and $minor -eq 10)
    } catch {
        return $false
    }
}

function Resolve-Python310 {
    if ($Python -and (Test-Path $Python)) {
        if (Test-Py310 $Python) { return $Python }
        throw "Not Python 3.10: $Python"
    }
    try {
        $py310 = (& py -3.10 -c "import sys; print(sys.executable)" 2>$null).Trim()
        if (Test-Py310 $py310) { return $py310 }
    } catch { }
    return $null
}

function Write-ActivateBat {
    param([string]$VenvRoot)
    $scripts = Join-Path $VenvRoot "Scripts"
    New-Item -ItemType Directory -Force -Path $scripts | Out-Null
    $lines = @(
        '@echo off',
        'set "VIRTUAL_ENV=%~dp0.."',
        'for %%I in ("%VIRTUAL_ENV%") do set "VIRTUAL_ENV=%%~fI"',
        'set "PATH=%VIRTUAL_ENV%;%VIRTUAL_ENV%\Scripts;%VIRTUAL_ENV%\Library\bin;%PATH%"',
        'if defined PROMPT (set "PROMPT=(venv) %PROMPT%") else (set "PROMPT=(venv) $P$G")'
    )
    Set-Content -Path (Join-Path $scripts "activate.bat") -Value $lines -Encoding ASCII
}

function Resolve-VenvPython {
    param([string]$VenvRoot)
    $candidates = @(
        (Join-Path $VenvRoot "Scripts\python.exe"),
        (Join-Path $VenvRoot "python.exe")
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    throw "python.exe not found under venv"
}

if (Test-Path $VenvDir) {
    if (-not $Force) {
        $ans = Read-Host "Backup old venv to venv.bak-* and recreate? [y/N]"
        if ($ans -notmatch '^[yY]') {
            Write-Host "Cancelled"
            exit 0
        }
    }
    $bakName = "venv.bak-" + (Get-Date -Format "yyyyMMdd_HHmmss")
    Write-Host "Backup: $bakName"
    Rename-Item -Path $VenvDir -NewName $bakName
}

$Py310 = Resolve-Python310
if ($Py310) {
    Write-Host "Create standard venv with: $Py310"
    & $Py310 -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
} else {
    $Conda = Find-Conda
    if (-not $Conda) {
        throw "Python 3.10 not found. Install Python 3.10 and run: recreate_venv_py310.bat -Python C:\path\python310.exe OR install Miniconda."
    }
    Write-Host "Create conda env (Python 3.10): $VenvDir"
    & $Conda create -y -p $VenvDir python=3.10 pip
    if ($LASTEXITCODE -ne 0) { throw "conda create failed" }
    Write-ActivateBat -VenvRoot $VenvDir
}

$Py = Resolve-VenvPython -VenvRoot $VenvDir
Write-Host "venv: $(& $Py --version)"

Write-Host "Installing requirements..."
& $Py -m pip install --upgrade pip
& $Py -m pip install -r $ReqFile
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $Py -m pip uninstall -y pyarmor pyarmor.cli.core *> $null
} finally {
    $ErrorActionPreference = $prevEap
}
& $Py -m pip install "pyarmor==7.7.4"

Write-Host ""
Write-Host "Done."
Write-Host "  Python: $Py"
Write-Host "  Next:   scripts\prepare_release.bat"
