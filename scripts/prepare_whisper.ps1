# Prepare Whisper deps for release builds: install CUDA PyTorch by default (CPU fallback at runtime).
# Skip torch reinstall when a CUDA wheel is already present.

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # ignore
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $Root "backend"
$VenvPythonCandidates = @(
    (Join-Path $Root "venv\Scripts\python.exe"),
    (Join-Path $BackendDir "venv\Scripts\python.exe")
)
$Py = ($VenvPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Py) { $Py = "python" }

$TorchVersion = $env:LX_TORCH_VERSION
if (-not $TorchVersion) { $TorchVersion = "2.11.0" }
$CudaIndex = $env:LX_TORCH_CUDA_INDEX
if (-not $CudaIndex) { $CudaIndex = "https://download.pytorch.org/whl/cu124" }

function Invoke-Py {
    param([string[]]$PyArgs)
    & $Py @PyArgs
    if ($LASTEXITCODE -ne 0) {
        throw ("pip/python failed: " + $Py + " " + ($PyArgs -join " "))
    }
}

function Test-TorchCudaWheel {
    try {
        $out = & $Py -c "import torch; print(torch.__version__); print(torch.version.cuda or '')" 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        $lines = @($out | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
        if ($lines.Count -lt 2) { return $false }
        return [bool]$lines[1]
    } catch {
        return $false
    }
}

function Ensure-WhisperDeps {
    Write-Host ('whisper: python=' + $Py)

    $hasCudaWheel = Test-TorchCudaWheel
    if ($hasCudaWheel) {
        Write-Host 'whisper: CUDA PyTorch wheel detected, skip reinstall'
    } else {
        Write-Host ('whisper: installing CUDA PyTorch ' + $TorchVersion + ' (CPU fallback at runtime if no GPU)')
        Invoke-Py -PyArgs @("-m", "pip", "install", "--upgrade", "pip")
        try {
            Invoke-Py -PyArgs @(
                "-m", "pip", "install", "--upgrade",
                ("torch==" + $TorchVersion),
                "--index-url", $CudaIndex
            )
        } catch {
            Write-Host ('whisper: CUDA index install failed, fallback to CPU torch: ' + $_.Exception.Message)
            Invoke-Py -PyArgs @("-m", "pip", "install", "--upgrade", ("torch==" + $TorchVersion))
        }
    }

    Write-Host 'whisper: ensure openai-whisper'
    Invoke-Py -PyArgs @("-m", "pip", "install", "--upgrade", "openai-whisper>=20231117")

    $CheckScript = Join-Path $PSScriptRoot "check_whisper_deps.py"
    $info = & $Py $CheckScript
    if ($LASTEXITCODE -ne 0) {
        throw 'whisper: dependency self-check failed'
    }
    Write-Host ('whisper: ' + ($info -join ' | '))
}

Ensure-WhisperDeps
