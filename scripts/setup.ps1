# One-time setup on a new PC.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File C:\FacebookLeadMonitor\scripts\setup.ps1
# Safe to run again: existing .venv and .env are kept.

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectDir
Write-Host "Project folder: $ProjectDir"

# 1. Python 3.12+ must be installed (python.org, tick "Add python.exe to PATH").
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python not found. Install Python 3.12+ from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
& python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.12 or newer is required. Found: $(& python --version)" -ForegroundColor Red
    exit 1
}
Write-Host "Python: $(& python --version)"

# 2. Virtual environment with dependencies.
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment .venv ..."
    & python -m venv .venv
}
Write-Host "Installing dependencies ..."
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed" -ForegroundColor Red; exit 1 }

# 3. Settings file (secrets are never stored in Git).
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env created from .env.example - fill in your tokens!" -ForegroundColor Yellow
} else {
    Write-Host ".env already exists - kept as is."
}

# 4. Quick self-check.
Write-Host "Running tests ..."
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "Some tests failed" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next: fill in .env, then load the 'extension' folder in chrome://extensions (see README.md)."
