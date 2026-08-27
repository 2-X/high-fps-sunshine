# Passive present-cadence capture of the LIVE Dolphin via PresentMon (the copy
# NVIDIA's FrameView SDK already ships -- nothing to install). ETW needs admin,
# so this pops ONE UAC prompt; the capture itself never touches the game --
# keep playing through it. Then run present_cadence.py on the CSV.
#
# Usage:  powershell -File pm_capture.ps1 [-Tag v25] [-Seconds 60]
param(
    [string]$Tag = "capture",
    [int]$Seconds = 60
)

$pm = "C:\Program Files\NVIDIA Corporation\FrameViewSDK\bin\PresentMon_x64.exe"
if (-not (Test-Path $pm)) { throw "PresentMon not found at $pm" }
if (-not (Get-Process Dolphin -ErrorAction SilentlyContinue)) {
    throw "Dolphin is not running"
}

$dataDir = Join-Path $PSScriptRoot "..\data"
New-Item -ItemType Directory -Force $dataDir | Out-Null
$dataDir = (Resolve-Path $dataDir).Path
$csv = Join-Path $dataDir "pm_$Tag.csv"
if (Test-Path $csv) { Remove-Item $csv -Force }

$pmArgs = @(
    "--process_name", "Dolphin.exe",
    "--output_file", "`"$csv`"",
    "--v1_metrics",
    "--timed", "$Seconds",
    "--terminate_after_timed",
    "--no_console_stats",
    "--stop_existing_session"
)
Write-Host "Capturing $Seconds s of present timing (UAC prompt incoming; keep playing)..."
$p = Start-Process -FilePath $pm -ArgumentList $pmArgs -Verb RunAs -Wait -PassThru
Write-Host "PresentMon exit code: $($p.ExitCode)"

if (Test-Path $csv) {
    $lines = (Get-Content $csv | Measure-Object -Line).Lines
    Write-Host "Wrote $csv ($lines rows). Analyzing..."
    python (Join-Path $PSScriptRoot "present_cadence.py") $csv
} else {
    Write-Host "No CSV produced -- did the UAC prompt get declined?"
}
