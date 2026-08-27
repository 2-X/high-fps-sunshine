# game_io.ps1 -- focus Dolphin render window, optionally send keys, screenshot it.
# Usage: game_io.ps1 [-Keys "space,space"] [-DelayMs 800] [-Shot out.png]
param(
    [string]$Keys = "",
    [int]$DelayMs = 800,
    [string]$Shot = ""
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  public struct RECT { public int L, T, R, B; }
}
"@

# The render window title contains the game id; fall back to the main window.
$procs = Get-Process Dolphin -ErrorAction SilentlyContinue
if (-not $procs) { throw "Dolphin not running" }
$target = $null
foreach ($p in $procs) {
    if ($p.MainWindowTitle -match 'GMSE01|FPS|Super Mario') { $target = $p; break }
}
if (-not $target) { $target = $procs[0] }
$h = $target.MainWindowHandle
if ($h -eq [IntPtr]::Zero) { throw "no main window handle" }
[void][Win32]::ShowWindow($h, 9)   # SW_RESTORE (no-op if not minimized)
[void][Win32]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 400
Write-Output "window: '$($target.MainWindowTitle)'"

if ($Keys -ne "") {
    foreach ($k in $Keys -split ',') {
        $tok = $k.Trim()
        switch ($tok) {
            'space'   { [System.Windows.Forms.SendKeys]::SendWait(" ") }
            'enter'   { [System.Windows.Forms.SendKeys]::SendWait("~") }
            'back'    { [System.Windows.Forms.SendKeys]::SendWait("{BACKSPACE}") }
            'up'      { [System.Windows.Forms.SendKeys]::SendWait("{UP}") }
            'down'    { [System.Windows.Forms.SendKeys]::SendWait("{DOWN}") }
            'left'    { [System.Windows.Forms.SendKeys]::SendWait("{LEFT}") }
            'right'   { [System.Windows.Forms.SendKeys]::SendWait("{RIGHT}") }
            'savest4' { [System.Windows.Forms.SendKeys]::SendWait("+{F4}") }
            'loadst4' { [System.Windows.Forms.SendKeys]::SendWait("{F4}") }
            default   { [System.Windows.Forms.SendKeys]::SendWait($tok) }
        }
        Start-Sleep -Milliseconds $DelayMs
    }
    Write-Output "sent: $Keys"
}

if ($Shot -ne "") {
    $r = New-Object Win32+RECT
    [void][Win32]::GetWindowRect($h, [ref]$r)
    $w = $r.R - $r.L; $ht = $r.B - $r.T
    if ($w -le 0 -or $ht -le 0) { throw "bad window rect" }
    $bmp = New-Object System.Drawing.Bitmap $w, $ht
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
    $bmp.Save($Shot, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "shot: $Shot ($w x $ht)"
}
