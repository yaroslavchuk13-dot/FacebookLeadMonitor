# Starts the program: server for the extension + Telegram bot (uses .venv, no activation needed).
# Run:  powershell -ExecutionPolicy Bypass -File C:\FacebookLeadMonitor\scripts\start_server.ps1
# Stop: Ctrl+C in this window.

$ProjectDir = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectDir

$python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No .venv found. Run scripts\setup.ps1 first." -ForegroundColor Red
    exit 1
}

& $python -m lead_monitor
exit $LASTEXITCODE
