# GroundProof one-command local start for Windows PowerShell.
# Usage (from the repo folder):  powershell -ExecutionPolicy Bypass -File .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# 1. Find Python 3.12+
$py = $null
foreach ($c in @("py -3.13", "py -3.12", "python")) {
  try { $v = & cmd /c "$c --version 2>&1"; if ($v -match "Python 3\.(1[2-9]|[2-9]\d)") { $py = $c; break } } catch {}
}
if (-not $py) { Write-Host "Python 3.12 or newer is required. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." -ForegroundColor Red; exit 1 }
Write-Host "Using $py" -ForegroundColor Green

# 2. Virtual environment + dependencies (first run takes a few minutes)
if (-not (Test-Path ".venv")) { & cmd /c "$py -m venv .venv" }
$venvPy = ".\.venv\Scripts\python.exe"
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -e ".\api[dev]"

# 3. Demo data, then start the server
$env:PYTHONPATH = "$PSScriptRoot\api;$PSScriptRoot"
$env:ICEYE_ENABLED = "true"
Set-Location "$PSScriptRoot\api"
& $venvPy -m app.demo
Write-Host ""
Write-Host "Open http://localhost:8000/console/  (use the Analyst / Buyer / Admin shortcuts on the login screen)" -ForegroundColor Green
Write-Host "Field app: http://localhost:8000/field/   |   API docs: http://localhost:8000/docs   |   Stop with Ctrl+C" -ForegroundColor Green
& $venvPy -m uvicorn app.main:app --port 8000
