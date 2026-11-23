# Shows database statistics and the latest leads.
# Run:  powershell -ExecutionPolicy Bypass -File C:\FacebookLeadMonitor\scripts\show_leads.ps1 [N]

param([int]$Count = 10)

$ProjectDir = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectDir
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

& (Join-Path $ProjectDir ".venv\Scripts\python.exe") -m lead_monitor.storage $Count
