$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".venv\Scripts\dealintel.exe")) { & "$PSScriptRoot\setup.ps1" }
& .\.venv\Scripts\dealintel.exe run
