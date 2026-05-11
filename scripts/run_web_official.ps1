$ErrorActionPreference = "Stop"

$appRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$srcDir = (Resolve-Path (Join-Path $appRoot "src")).Path
$webDir = (Resolve-Path (Join-Path $appRoot "web")).Path

Set-Location -LiteralPath $appRoot
$env:PYTHONPATH = $srcDir

python -m uvicorn motion_api.main:app --reload --reload-dir $srcDir --reload-dir $webDir
