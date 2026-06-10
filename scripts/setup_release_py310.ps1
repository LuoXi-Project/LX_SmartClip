param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
chcp 65001 > $null

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvDir = Join-Path $Root "venv-py310"
$ReqFile = Join-Path $Root "backend\requirements.txt"

function Find-Python310 {
    param([string]$Explicit)
    if ($Explicit -and (Test-Path $Explicit)) { return $Explicit }
    $candidates = @(
        $env:LX_RELEASE_PYTHON,
        $env:LX_PYARMOR_PYTHON
    ) | Where-Object { $_ -and (Test-Path $_) }
    foreach ($c in $candidates) { return $c }

    try {
        $exe = (& py -3.10 -c "import sys; print(sys.executable)" 2>$null).Trim()
        if ($exe) { return $exe }
    } catch { }

    throw @"
未找到 Python 3.10。PyArmor 7 仅支持 Python 3.7–3.10。

请先安装 Python 3.10（勾选 Add to PATH），然后重试：
  scripts\setup_release_py310.ps1

或指定解释器：
  scripts\setup_release_py310.ps1 -Python C:\Path\To\python310.exe
"@
}

$PyExe = Find-Python310 -Explicit $Python
Write-Host "使用 Python: $PyExe"

if (Test-Path $VenvDir) {
    Write-Host "删除旧 venv-py310 ..."
    Remove-Item $VenvDir -Recurse -Force
}

Write-Host "创建 venv-py310 ..."
& $PyExe -m venv $VenvDir
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "安装 backend 依赖（含 pyarmor==7.7.4）..."
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r $ReqFile
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $VenvPy -m pip uninstall -y pyarmor pyarmor.cli.core *> $null
} finally {
    $ErrorActionPreference = $prevEap
}
& $VenvPy -m pip install "pyarmor==7.7.4"

$ver = & $VenvPy -c "import sys, pyarmor; print(sys.version.split()[0], 'pyarmor', pyarmor.__version__)"
Write-Host ""
Write-Host "完成: $ver"
Write-Host "发版打包将自动使用: $VenvPy"
Write-Host ""
Write-Host "下一步: scripts\prepare_release.bat"
