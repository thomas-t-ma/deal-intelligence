$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".venv")) { py -3.13 -m venv .venv 2>$null; if ($LASTEXITCODE -ne 0) { py -3 -m venv .venv } }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .
& .\.venv\Scripts\dealintel.exe init
Write-Host ""
Write-Host "Setup complete. Run: .\scripts\run.ps1" -ForegroundColor Green
