# SETUP — 120fps ONLINE CLIENT (fresh Windows PC)

**Audience:** a Claude Code session (or a patient human) on a new Windows machine that
wants to JOIN a BSMSO online session at 120fps. Written 2026-08-27 for Kris's brother's
PC and John. The host side (server, port, firewall) already runs on Kris's PC — you
only need the client stack.

## What you need before starting

1. **This repo** (public): `git clone https://github.com/2-X/high-fps-sunshine C:\code\high-fps-sunshine`
   then `git checkout fpspatch-generalize`. Clone to that EXACT path — several research
   scripts hardcode it, and matching the host's layout keeps every doc's paths valid.
2. **`dolphin-hifps-win64.zip`** (~29MB) — the patched Dolphin fork build (gitignored,
   not in the repo; Kris distributes it — UGREEN share or direct send). Contains
   `Dolphin.exe` at the zip root. GPL source = `sunshine/dolphin-patches/` on the
   upstream commit in `UPSTREAM_COMMIT.txt`.
3. **The game**: `BSMSO-GMSE01-highfps.iso` (Super Mario Sunshine USA with the BSMSO
   online kxe modules injected). Not distributed with this kit — it contains Nintendo's
   game. Get it from Kris privately, or build from your own legally-dumped SMS copy
   (see `sunshine/bsmso/` docs).
4. **Python 3.12+** on PATH.
5. A **controller** (Xbox pad works out of the box; keyboard is playable but rough).

## Install steps

1. Unzip `dolphin-hifps-win64.zip` into `C:\code\high-fps-sunshine\dolphin-src\Binary\x64\`
   (so `...\Binary\x64\Dolphin.exe` exists). **The `dolphin-src` folders will NOT
   exist after cloning — they're gitignored. Create them** (`mkdir
   C:\code\high-fps-sunshine\dolphin-src\Binary\x64` first, or extract the zip
   there with "extract to" pointing at that path).
2. Put the ISO somewhere sane, e.g. `C:\sms\bsmso-work\BSMSO-GMSE01-highfps.iso`.
3. `pip install -r C:\code\high-fps-sunshine\sunshine\launcher\requirements.txt`
4. Create `C:\code\high-fps-sunshine\sunshine\launcher\config.local.json`
   (copy `config.local.json.example`), Windows values:

   ```json
   {
     "iso_dir":     "C:\\sms\\bsmso-work",
     "dolphin_app": "C:\\code\\high-fps-sunshine\\dolphin-src\\Binary\\x64\\Dolphin.exe",
     "server_addr": "<HOST ADDRESS — see Network below>"
   }
   ```

5. Launch once so Dolphin creates its config dir (`%APPDATA%\Dolphin Emulator`), set
   up your controller in Dolphin's Controllers dialog, then quit.
6. The real launch:
   `cd C:\code\high-fps-sunshine\sunshine\launcher; python drive_launcher.py "Online 120"`
   — it writes the INI (120fps bundle, EmulationSpeed 2.0, 64MB MEM1 override), boots
   the BSMSO ISO, and starts your bridge automatically.
7. Pick a save, get INTO A STAGE (Delfino Plaza). The bridge only attaches in a stage —
   "comm buffer not found" on the title screen is NORMAL, not a failure.

Success = the other players' Marios appear near you, and yours on their screens.

## Network — what goes in `server_addr`

- **Same LAN as the host PC:** the host's LAN IP. As of 2026-08-27 that is
  **`192.168.4.58`** (it CHANGED from the 192.168.1.20 in older docs — if joining
  fails, re-ask the host, IPs drift). Port `27015` TCP **and** UDP; the host firewall
  already allows it.
- **Remote over the internet (John):** don't expose raw internet unless chosen —
  pick one with the host:
  - **Radmin VPN or Tailscale** (both free): host + client install it, join the same
    network, then `server_addr` = the host's VPN IP. Easiest and safest.
  - **Port forward**: host forwards 27015 TCP+UDP → 192.168.4.58 on their router and
    gives you their public IP. Fails silently if the host ISP uses CGNAT.
  - Note: the host runs NordVPN — that's an outbound tunnel and does not carry inbound
    game traffic; it is NOT the VPN you join.

## Gotchas (paid for already — don't re-pay)

- Dolphin rewrites `GMSE01.ini` from memory on quit — never hand-edit it while running.
- BSE cold-boots 30fps/4:3 every launch; the launcher's Gecko writes force the rate.
  Don't panic at a 30fps title screen.
- "Cannot find MEM1" while NOT in a booted game is normal (emulation stopped = nothing
  mapped). Verify the window title shows `GMSE01` before debugging the memory backend.
- Every player needs a UNIQUE bridge name (the launcher uses the profile's
  `player_name` — set it to your own name in `sunshine/launcher/profiles.json`,
  "Online 120" profile, or the puppets collide).
- Per-player FPS is local (position sync, not lockstep): your 120 happily joins the
  host's 240.
- **`GFX FIFO: Unknown Opcode (0x.. @ ..)` desync / crash:** the high-fps hack stresses
  the FIFO enough to trip a dual-core GPU/CPU-thread race on some clients. The kit's
  `Dolphin.ini.pc` already ships the fix — loose SyncGPU (`SyncGPU = True`,
  `SyncGpuMaxDistance = 1000000`, `SyncGpuMinDistance = -1000000` under `[Core]`), which
  keeps dual-core speed. If you copied an older config or still desync on a weak GPU,
  add those lines (Dolphin closed — it rewrites the INI on quit), or as a last resort
  set `CPUThread = False` (single core: no desync, slower).

## Paste-prompt for a fresh Claude chat on the client PC

> You are setting up this Windows PC as a 120fps BSMSO online client for Super Mario
> Sunshine. Follow `sunshine/SETUP-CLIENT-120.md` in the repo
> `2-X/high-fps-sunshine` (branch `fpspatch-generalize`) step by step. I have the
> dolphin zip and the ISO at: <FILL IN PATHS>. The server address is: <FILL IN>.
> Verify each step, and when the game is in Delfino Plaza confirm the bridge attached
> (its log says so) and report what you see.
