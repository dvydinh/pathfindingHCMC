$root = $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:DATA_DIR   = "$root\data"
$env:CONFIG_DIR = "$root\config"
$env:PYTHONPATH = "$root\services\api"
Write-Host "env OK: $env:CONFIG_DIR"
