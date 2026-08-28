# SETUP — 120fps ONLINE CLIENT (fresh Windows PC) — verification-driven

**Audience:** a Claude Code session (or a careful human) on a new Windows machine
joining a BSMSO online Super Mario Sunshine session at 120fps. The host (server,
port 27015 TCP+UDP, firewall) already runs on Kris's PC. Every step below ends
with a **VERIFY** — do not move on until it passes. Written 2026-08-27/28 for
Kris's brother's PC (LAN) and John (remote).

## What you need in hand before starting

| # | Thing | Where it comes from |
|---|-------|---------------------|
| 1 | This repo | public: `https://github.com/2-X/high-fps-sunshine`, branch `fpspatch-generalize` |
| 2 | `dolphin-hifps-win64.zip` (~29MB) | from Kris (in `sms-online-kit.zip`); the patched fork build, gitignored, NOT in the repo |
| 3 | `BSMSO-GMSE01-highfps.iso` (~1,392MB) | from Kris privately (WeTransfer/UGREEN, zipped ~1,044MB). **A stock/downloaded SMS ISO will NOT work** — the online mod's kxe modules are injected into this specific disc; the bridge finds nothing on a stock copy |
| 4 | Git + Python 3.12+ | `winget install Git.Git Python.Python.3.12` |
| 5 | A controller | Xbox pad = zero config beyond Dolphin's controller dialog |
| 6 | (remote players only) Radmin VPN or Tailscale | see Network section — Kris must run the same one |

## Install steps — each with its VERIFY

**1. Clone the repo to the EXACT path** (scripts reference it):

```powershell
git clone https://github.com/2-X/high-fps-sunshine C:\code\high-fps-sunshine
git -C C:\code\high-fps-sunshine checkout fpspatch-generalize
```

VERIFY: `git -C C:\code\high-fps-sunshine log --oneline -1` prints a commit, and
`Test-Path C:\code\high-fps-sunshine\sunshine\launcher\drive_launcher.py` is True.

**2. Create the Dolphin folder tree and unzip the build into it.** The
`dolphin-src` tree is gitignored — a fresh clone does NOT contain it; you create it:

```powershell
New-Item -ItemType Directory -Force C:\code\high-fps-sunshine\dolphin-src\Binary\x64
Expand-Archive dolphin-hifps-win64.zip -DestinationPath C:\code\high-fps-sunshine\dolphin-src\Binary\x64
```

VERIFY: `Test-Path C:\code\high-fps-sunshine\dolphin-src\Binary\x64\Dolphin.exe`
is True (the exe directly in `x64\`, NOT in a nested subfolder — if Expand-Archive
nested it, move the contents up one level).

**3. Place the game:**

```powershell
New-Item -ItemType Directory -Force C:\sms\bsmso-work
# put/extract BSMSO-GMSE01-highfps.iso there
```

VERIFY: `(Get-Item C:\sms\bsmso-work\BSMSO-GMSE01-highfps.iso).Length` is
~1,460,000,000 bytes (±1%). A ~4.7GB file is a full-disc dump and wrong; a file
named anything else is wrong.

**4. Python deps:**

```powershell
pip install -r C:\code\high-fps-sunshine\sunshine\launcher\requirements.txt
```

VERIFY: exits without error.

**5. Config.** Create `C:\code\high-fps-sunshine\sunshine\launcher\config.local.json`:

```json
{
  "iso_dir":     "C:\\sms\\bsmso-work",
  "dolphin_app": "C:\\code\\high-fps-sunshine\\dolphin-src\\Binary\\x64\\Dolphin.exe",
  "server_addr": "<see Network section>"
}
```

- LAN (same house as Kris): `"192.168.4.58"`
- Remote over VPN (John): Kris's **Radmin/Tailscale IP** (Kris reads it off his
  VPN client and tells you; Radmin IPs look like `26.x.x.x`)

VERIFY: `python -c "import json; print(json.load(open(r'C:\code\high-fps-sunshine\sunshine\launcher\config.local.json'))['server_addr'])"` prints the address.

**6. Network reachability** (the step most "it doesn't connect" reports actually are):

- LAN: nothing to install.
- Remote: install the SAME VPN as Kris (Radmin VPN: create/join his network with
  the name+password he gives you; Tailscale: sign in, he shares his machine).

VERIFY: `Test-NetConnection <server_addr> -Port 27015` shows `TcpTestSucceeded : True`.
If False, the game cannot work — stop and fix this first (wrong IP, VPN not
connected, or Kris's server/firewall down). Do NOT proceed to debug Dolphin.

**7. First Dolphin run — controller + config dir:**

Run `C:\code\high-fps-sunshine\dolphin-src\Binary\x64\Dolphin.exe` once, set up
your controller (Controllers → Port 1 → Standard Controller → map your pad),
then **quit Dolphin fully**.

Then add the FIFO-desync guard (with Dolphin CLOSED — it rewrites INIs on quit):
in `%APPDATA%\Dolphin Emulator\Config\Dolphin.ini` under `[Core]`, ensure:

```ini
SyncGPU = True
SyncGpuMaxDistance = 1000000
SyncGpuMinDistance = -1000000
```

(High-fps stresses the FIFO into a dual-core "GFX FIFO: Unknown Opcode" crash on
some machines; loose SyncGPU prevents it at ~no speed cost. Template:
`sunshine/dolphin-config/Dolphin.ini.pc`.)

**User-directory trap (John hit this):** Dolphin's user dir is not reliably
`%APPDATA%\Dolphin Emulator` — a legacy `Documents\Dolphin Emulator` from an old
install silently wins, and then every INI edit lands in a file the emulator
never reads. Check for it; if present, rename it away:

```powershell
if (Test-Path "$([Environment]::GetFolderPath('MyDocuments'))\Dolphin Emulator") {
  Rename-Item "$([Environment]::GetFolderPath('MyDocuments'))\Dolphin Emulator" "Dolphin Emulator.OLD"
}
```

VERIFY: `%APPDATA%\Dolphin Emulator\Config\Dolphin.ini` exists and contains the
three lines; no `Documents\Dolphin Emulator` folder exists; Dolphin is not
running. (Cross-check after step 9: the launcher's settings visibly took —
window title shows the game, fps counter far above 30 in-game.)

**8. Your player name** — every player needs a UNIQUE one. In
`C:\code\high-fps-sunshine\sunshine\launcher\profiles.json`, find the profile
named `"Online 120"` and set its `"player_name"` to YOUR name (e.g. `"John"`).

VERIFY: `python -c "import json; print([p['player_name'] for p in json.load(open(r'C:\code\high-fps-sunshine\sunshine\launcher\profiles.json'))['profiles'] if p['name']=='Online 120'])"` prints your name.

**9. Launch:**

```powershell
cd C:\code\high-fps-sunshine\sunshine\launcher
python drive_launcher.py "Online 120"
```

The launcher writes the game INI (120fps bundle + perf gates + guards +
EmulationSpeed 2.0 + 64MB MEM1 override), boots the BSMSO ISO, and starts your
bridge automatically.

VERIFY (in the launcher output): a line `Enabled N codes:` that includes
`$J3D duplicate-entry guard v3`, `$EFB peek 30Hz gate BSE-120`, and
`$Noki pollution 30Hz gate BSE-120 v6` — plus `Starting bridge (name=<YOU>, fps=120)…`.

**10. Get in the game:** pick a save file, walk into **Delfino Plaza**. The
bridge only attaches inside a stage — "comm buffer not found" on the title
screen is NORMAL and not a failure.

FINAL VERIFY: other players' Marios appear near you, and yours appears on their
screens. Solo check while nobody else is on:
`python C:\code\high-fps-sunshine\sunshine\bsmso\mac-online\winmem.py --verify-write`
(run while standing in the Plaza) reports success.

## Troubleshooting — in order of likelihood

| Symptom | Cause / fix |
|---|---|
| `Test-NetConnection` port 27015 False | Wrong `server_addr`, VPN not joined, or host down. Fix before anything else. Kris's LAN IP CHANGED 2026-08-27: `192.168.4.58` (older docs said 192.168.1.20 — dead). |
| Title screen runs at 30fps / 4:3 | Normal. BSE cold-boots 30fps; the rate is forced once you're in-game. |
| "comm buffer not found" / "cannot find MEM1" | You're on the title screen or emulation stopped. Be IN A STAGE; window title must contain `GMSE01`. |
| `GFX FIFO: Unknown Opcode` crash | Step 7's SyncGPU lines missing. Add them (Dolphin closed). Last resort: `CPUThread = False` (slower, bulletproof). |
| Other players frozen in place | Their side disconnected/relaunched — restart YOUR bridge (relaunch via step 9). Known bridge limitation. |
| Codes don't seem active after hand-editing INIs | Dolphin rewrites `GMSE01.ini` from memory on quit — never edit while it runs; the launcher manages it, prefer step 9 over hand edits. |
| INI edits have NO effect at all (not even wrong ones) | Legacy `Documents\Dolphin Emulator` dir is shadowing `%APPDATA%` — see the user-directory trap in step 7. |
| Double/triple jump nearly impossible at 120 | Known engine bug, not your setup: the jump-chain window shrinks with the BSE rate (`sunshine/HANDOFF-JUMPCHAIN-BUG.md`). Fix in progress — pull the repo for updates. |
| fps struggles at 120 | Make sure the step-9 VERIFY showed the two perf gates (peek + Noki v6) enabled — they are the difference between ~always-120 and Bianco slideshows. Pull the repo if missing (`git pull`), relaunch. |
| Bursty hitching (fast/hitch/fast) especially first time in a level | Shader-compilation stutter with a cold cache. The kit's `GFX.ini.pc` now ships `ShaderCompilationMode = 3` + `ShaderCache = True` — confirm your `%APPDATA%\Dolphin Emulator\Config\GFX.ini` `[Settings]` has them (Dolphin closed; mode `0` = the stutter-prone default). Smooths out further as the on-disk cache fills over the first playthrough. |

## Handoff prompt for the AI on the client PC — paste this into a fresh Claude Code chat

> You are setting up this Windows PC as a 120fps BSMSO online client for Super
> Mario Sunshine, following `sunshine/SETUP-CLIENT-120.md` in the repo
> `2-X/high-fps-sunshine` (branch `fpspatch-generalize`) — clone the repo first
> if it isn't at `C:\code\high-fps-sunshine` yet, then open that file and follow
> it EXACTLY, running every VERIFY and not advancing past a failed one.
> My materials: dolphin-hifps-win64.zip is at <FILL IN>, the BSMSO ISO (or its
> zip) is at <FILL IN>. My player name is <FILL IN>. The server address is
> <FILL IN — 192.168.4.58 on Kris's LAN, or Kris's Radmin/Tailscale IP if I'm
> remote; if I don't know it, stop and tell me to ask Kris>.
> Steps 6 and 7 need my involvement (VPN join, controller mapping) — tell me
> exactly what to do when you reach them. When the game is in Delfino Plaza,
> confirm the bridge attached and give me a short status report: enabled-codes
> check, network check, and what you see.
