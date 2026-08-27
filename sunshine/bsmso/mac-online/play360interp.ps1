# play360interp.ps1 - launch the NEVER-YET-TESTED 360Hz interpolated mode:
# locked 180fps game logic + 2:1 frame blending to 360 presents.
#
# Background (sunshine\HOWTO-INTERPOLATION-360.md has the full story): native
# 360 emulation is host-limited to ~303fps on this PC (Video-thread bound,
# measured 2026-08-20) and runs the game in slow motion. The fork has carried
# a frame-interpolation feature since July (Present.cpp) gated SOLELY by the
# DOLPHIN_FRAME_INTERP environment variable - no INI key, no GUI. 180 logic
# x2 blending = correct game speed AND a true 360Hz image. Expect possible
# ghosting on fast motion (linear crossfade, untested in play).
#
# PREREQUISITE: the live INI must already be configured for 180 offline -
# run the smslaunch TUI, launch "offline 180", then QUIT Dolphin, then run
# this script. (The env var must be set before launch; the TUI doesn't set it.)
#
# VERIFYING IT WORKS:
#   * Dolphin's own FPS counter will still read ~180 - it counts emulated
#     frames, not presents. Use RTSS / GPU driver overlay to confirm ~360.
#   * The feature logs to stderr: check %TEMP%\sms-interp.log for
#     "[FRAME_INTERP] factor = 2" and heartbeat lines.
$ErrorActionPreference = "Stop"
$Dolphin = "C:\code\high-fps-sunshine\dolphin-src\Binary\x64\Dolphin.exe"
$Iso = "C:\Users\krisb\kris-documents\games\dolphin\Super Mario Sunshine (USA).rvz"
$GameIni = "$env:APPDATA\Dolphin Emulator\GameSettings\GMSE01.ini"

if (Get-Process Dolphin -ErrorAction SilentlyContinue) {
    throw "Dolphin is running - quit it first (this script never kills your session)."
}
$speed = (Select-String -Path $GameIni -Pattern "^EmulationSpeed *= *(.+)$").Matches.Groups[1].Value.Trim()
if ($speed -ne "3.0" -and $speed -ne "3") {
    throw "EmulationSpeed is $speed, not 3.0 - configure 180 offline first (smslaunch TUI: offline 180, then quit Dolphin, then rerun this)."
}
$env:DOLPHIN_FRAME_INTERP = "2"
$log = Join-Path $env:TEMP "sms-interp.log"
Start-Process -FilePath $Dolphin -ArgumentList @('-e', "`"$Iso`"") `
    -RedirectStandardError $log
Write-Host "[interp] launched: 180 logic x2 blend -> 360Hz presents."
Write-Host "[interp] stderr log: $log  (expect '[FRAME_INTERP] factor = 2')"
Write-Host "[interp] Dolphin's FPS counter will read ~180 - that is CORRECT."
Write-Host "[interp] Confirm 360 presents with RTSS/driver overlay; watch for ghosting."
