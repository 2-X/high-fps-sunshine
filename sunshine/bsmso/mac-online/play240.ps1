# play240.ps1 - Windows launcher for the BSMSO high-fps fork ISO.
# Pick a framerate and go:  -Fps 30|60|120|240|280|320
#
# The Windows counterpart to play120.sh / the Mac smslaunch TUI.
#
# WHAT A LAUNCH DOES (close -> configure -> boot -> verify)
#   1. Quit Dolphin (it rewrites the per-game INI from memory on quit and would
#      clobber every edit made while it runs).
#   2. switch_rate.py does the whole rate change in one shot: companion bundle
#      regenerated FRESH from fpspatch --bse (stale stored bundles bite
#      silently - the 2026-08-14 Mac lesson), static codes (menu key-repeat v2,
#      DuneBud null-guard), bse_force.py's `04` force-writes, and
#      EmulationSpeed = FPS/60 in both INIs.
#   3. Boot the fork ISO and wait for the game window.
#   4. smslaunch.verify attaches to live memory and PROVES every enabled code
#      installed + the framerate global holds FPS/60 - a silently-dead code
#      list looks identical to a working one (the bracket-title bug shipped
#      that way once).  Result: %TEMP%\sms-verify.log
#
# WHY GECKO 04 WRITES AND NOT A BOOT-TIME POKE
#   BSE cold-boots at 30fps / 4:3 on EVERY launch - neither setting persists to
#   the memory card.  With Dolphin's EmulationSpeed at FPS/60, that makes the
#   game run FPS/30 times too fast until BSE is told otherwise.  The code
#   handler applies 04 writes from the first frame, so mFPSValue, the aspect
#   setting, and the two stock timestep globals (0x804167B8, 0x80414904) are
#   correct in menus AND in gameplay.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File play240.ps1
#   powershell -ExecutionPolicy Bypass -File play240.ps1 -Fps 120
#   powershell -ExecutionPolicy Bypass -File play240.ps1 -Fps 280 -Aspect 2

param(
    [ValidateSet(30, 60, 120, 240, 280, 320)]
    [int]$Fps = 240,

    # BSE aspect enum: 0=4:3, 2=16:10, 3=16:9 (WIDE), 4=21:9.  -1 to skip.
    [int]$Aspect = 3,

    [switch]$SkipCodes,

    [string]$Dolphin = "C:\code\high-fps-sunshine\dolphin-src\Binary\x64\Dolphin.exe",
    [string]$Iso = "C:\Users\krisb\kris-documents\games\dolphin\bsmso-work\BSMSO-GMSE01-highfps.iso"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

foreach ($p in @($Dolphin, $Iso)) {
    if (-not (Test-Path $p)) { throw "Not found: $p" }
}

# Dolphin's EmulationSpeed must match the target rate (FPS/60) or the console
# runs at the wrong VPS regardless of what BSE thinks.
$speed = [math]::Round($Fps / 60.0, 6)

# --- 1. Quit Dolphin ------------------------------------------------------
if (Get-Process Dolphin -ErrorAction SilentlyContinue) {
    Write-Host "[play$Fps] closing running Dolphin..."
    taskkill /IM Dolphin.exe | Out-Null
    $n = 0
    while ((Get-Process Dolphin -ErrorAction SilentlyContinue) -and $n -lt 15) {
        Start-Sleep -Seconds 1; $n++
    }
    # Emulation is stopped by now; a hard kill is safe and, unlike a graceful
    # quit, leaves our INI edits alone instead of being rewritten from memory.
    if (Get-Process Dolphin -ErrorAction SilentlyContinue) {
        taskkill /F /IM Dolphin.exe | Out-Null
        Start-Sleep -Seconds 2
    }
    if (Get-Process Dolphin -ErrorAction SilentlyContinue) {
        throw "Dolphin would not exit; close it manually and retry."
    }
}

# --- 2. Configure the whole kit for this rate ------------------------------
if (-not $SkipCodes) {
    Push-Location $here
    try {
        # switch_rate.py = companion bundle (fresh from fpspatch --bse) + menu
        # key-repeat v2 + DuneBud null-guard + bse_force.py 04 writes +
        # EmulationSpeed in both INIs.  gecko.py is idempotent, so switching
        # rates replaces the previous rate's blocks.
        python switch_rate.py --fps $Fps --aspect $Aspect
        if ($LASTEXITCODE -ne 0) { throw "switch_rate.py failed" }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[play$Fps] -SkipCodes: EmulationSpeed should be $speed (Dolphin.ini / per-game [Core])"
}

# --- 3. Launch ------------------------------------------------------------
Write-Host "[play$Fps] launching $(Split-Path -Leaf $Iso)"
Start-Process -FilePath $Dolphin -ArgumentList @("-e", $Iso)

$n = 0
while ($n -lt 60) {
    Start-Sleep -Seconds 1; $n++
    $p = Get-Process Dolphin -ErrorAction SilentlyContinue
    if ($p -and $p.MainWindowTitle -match "GMSE01") { break }
}
$p = Get-Process Dolphin -ErrorAction SilentlyContinue
if (-not ($p -and $p.MainWindowTitle -match "GMSE01")) {
    throw "Game did not boot within ${n}s (title: '$($p.MainWindowTitle)')"
}
Write-Host "[play$Fps] booted after ${n}s - $Fps fps should be live from the first frame."

# --- 4. Post-launch verification (detached) --------------------------------
# Proves every enabled Gecko code actually installed and the framerate global
# holds FPS/60.  Without this, a silently-dead code list looks identical to a
# working one.  Reads its verdict ~30s from now: %TEMP%\sms-verify.log
$launcherDir = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $here))) "sunshine\launcher"
$verifyLog = Join-Path $env:TEMP "sms-verify.log"
Start-Process -WindowStyle Hidden -FilePath python `
    -ArgumentList @("-m", "smslaunch.verify", "--fps", "$Fps") `
    -WorkingDirectory $launcherDir `
    -RedirectStandardOutput $verifyLog -RedirectStandardError "$verifyLog.err"
Write-Host "[play$Fps] verify scheduled (~30s) - result: $verifyLog"
