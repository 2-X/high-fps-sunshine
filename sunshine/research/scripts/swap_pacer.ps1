# A/B the interp pacer build in Binary\x64 (HANDOFF-360-INTERP.md step 1).
# Refuses to run while Dolphin is open. Keeps the v2.5 exe as a named backup
# so the swap is reversible in one command.
#
#   powershell -File swap_pacer.ps1 -To v3     # stage the untested v3 build
#   powershell -File swap_pacer.ps1 -To v25    # roll back to the stable build
param(
    [Parameter(Mandatory)][ValidateSet("v3", "v25")][string]$To
)

if (Get-Process Dolphin -ErrorAction SilentlyContinue) {
    throw "Dolphin is running -- quit it first (the copy would fail or corrupt)."
}

$binDir = "C:\code\high-fps-sunshine\dolphin-src\Binary\x64"
$live = Join-Path $binDir "Dolphin.exe"
$v25Backup = Join-Path $binDir "Dolphin_v25_pacer.exe"
$v3Build = "C:\code\high-fps-sunshine\dolphin-src\Build\x64\Release\Dolphin\bin\Dolphin.exe"

if ($To -eq "v3") {
    if (-not (Test-Path $v3Build)) { throw "v3 build missing at $v3Build" }
    if (-not (Test-Path $v25Backup)) {
        Copy-Item $live $v25Backup
        Write-Host "Backed up current exe -> Dolphin_v25_pacer.exe"
    }
    Copy-Item $v3Build $live -Force
    Write-Host ("Binary\x64\Dolphin.exe is now the v3 pacer build (" +
        (Get-Item $live).LastWriteTime + ")")
} else {
    if (-not (Test-Path $v25Backup)) { throw "no v2.5 backup at $v25Backup" }
    Copy-Item $v25Backup $live -Force
    Write-Host ("Binary\x64\Dolphin.exe rolled back to v2.5 (" +
        (Get-Item $live).LastWriteTime + ")")
}
Write-Host "Launch as usual (play360interp.ps1); verify with pm_capture.ps1 + live_bench.py."
