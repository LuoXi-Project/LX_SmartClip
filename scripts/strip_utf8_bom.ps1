# 一键去除后端（或指定路径）Python 源码的 UTF-8 BOM，避免 PyArmor / AST 解析失败
$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # ignore
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPythonCandidates = @(
    (Join-Path $Root "venv\Scripts\python.exe"),
    (Join-Path $Root "backend\venv\Scripts\python.exe")
)
$Py = ($VenvPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Py) { $Py = "python" }

$Script = Join-Path $PSScriptRoot "strip_utf8_bom.py"
& $Py $Script @args
exit $LASTEXITCODE
