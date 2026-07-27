param(
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = "$root\src"
$env:QINGYAN_PORT = "$Port"

Write-Host "Starting Qingyan Liangce at http://localhost:$Port"
python run.py
