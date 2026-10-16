# Steam Deck (SteamOS / Linux) kit

Runs the high-fps Sunshine kit on a Steam Deck from Gaming Mode: one library
entry for offline 120fps (stock disc + fpspatch bundle) and one for online
120fps (BSMSO disc + bridge). It is the Linux counterpart to `play120.sh` /
`play240.ps1` and reuses the same launcher (`smslaunch`), `switch_rate.py` and
bridge.

**No game files are included.** You supply your own NTSC-U (GMSE01) dump, and
for online the BSMSO disc from the host's kit.

## What lives here

| File | Role |
|---|---|
| `build-dolphin.sh` | Builds the patched Dolphin inside the Dolphin Flatpak sandbox with the KDE SDK as toolchain (SteamOS has no compiler). Output: `dolphin/build/Binaries/Dolphin`. |
| `dolphin-deck` | The launcher's `dolphin_app`: runs that build in the Flatpak runtime with a dedicated user dir (`-u`) in batch mode (`-b`). |
| `setup.py` | Creates the user dir `~/.local/share/sms-high-fps/dolphin`, installs the config kit, writes `launcher/config.local.json` + `profiles.local.json` (`Deck Offline 120`, `Deck Online 120`, `Deck Solo 120`). |
| `deck_launch.py` | Preflight (disc / server / build), configure, boot, wait for Dolphin to exit, stop the bridge. `--check` = preflight only. |
| `sms-deck` | Steam entry point: `sms-deck offline` / `sms-deck online` / `sms-deck solo`. Logs to `~/.local/share/sms-high-fps/logs/`. |
| `add-steam-shortcuts.py` | Adds both entries to the running Steam client (no restart). |

Linux pieces elsewhere in the repo: `bsmso/mac-online/linuxmem.py` (memory
backend, picked by `gcmem.py`), the Linux branch in `smslaunch/launcher.py`,
and the `SMS_DOLPHIN_USER` override in `gecko.py` / `switch_rate.py`.

## Setup

```bash
# 1. toolchain + source (once)
flatpak install --user flathub org.kde.Sdk//6.10   # the "Sdk:" of `flatpak info org.DolphinEmu.dolphin-emu`
git clone https://github.com/dolphin-emu/dolphin dolphin        # at the repo root
git -C dolphin checkout $(cut -d' ' -f1 sunshine/dolphin-patches/UPSTREAM_COMMIT.txt)
git -C dolphin apply ../sunshine/dolphin-patches/high-fps-dolphin.patch
git -C dolphin submodule update --init --recursive --depth 1

# 2. build, configure, add to Steam
sunshine/deck/build-dolphin.sh
sunshine/deck/setup.py
sunshine/deck/add-steam-shortcuts.py
```

Then put the discs where the launcher looks:

| Mode | File | Where |
|---|---|---|
| offline | your GMSE01 dump, any name containing "Sunshine" (`.iso` / `.rvz`) | `~/Emulation/roms/gc/` |
| online, solo | `BSMSO-GMSE01-highfps.iso` (or `BSMSO-GMSE01.iso`) | `~/Emulation/roms/gc/bsmso-work/` |

`solo` boots the BSMSO disc single-player (BSE moveset, no server or bridge) —
the offline option when you only have the BSMSO discs. With both BSMSO discs
present the launcher boots the plain one at 120 and below, the fork at 240+.

Online either **hosts** on the Deck or **joins** another machine:

- **Host (default, no `server_addr` set).** Needs the server bundle and a
  .NET runtime, both outside the repo:

  ```bash
  unzip bundle-server.zip -d sunshine/bsmso/      # -> sunshine/bsmso/bundle-server/SMSO.ServerHost.dll
  # the Mac handoff zip is named bsmso-server.zip and unpacks to bsmso-server/ — rename it:
  #   unzip bsmso-server.zip && mv bsmso-server sunshine/bsmso/bundle-server
  curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- \
      --channel 10.0 --runtime aspnetcore --install-dir ~/.dotnet
  ```

  The launcher starts `SMSO.ServerHost.dll` with the game (nice 19), prints
  the Deck's LAN IP for the other players to use as their `server_addr`, and
  stops the server again when Dolphin exits. SteamOS's firewall already
  allows 27015 (ports 1024+ are open in the `public` zone).
- **Join.** Put the host in `launcher/config.local.json`:
  `"server_addr": "<IP of the machine running the BSMSO server>"` (27015 TCP+UDP).

`sunshine/deck/deck_launch.py offline --check` (or `online --check`) reports
exactly what is still missing.

## Notes

- **Process name.** The build is symlinked as `Dolphin` so every
  `pgrep -x Dolphin` guard in the repo matches it and nothing ever touches a
  stock `dolphin-emu` running alongside.
- **Memory access.** SteamOS sets `kernel.yama.ptrace_scope=1`, so
  `/proc/<pid>/mem` is off limits. `linuxmem.py` instead maps Dolphin's RAM
  arena (a shm object) through `/proc/<pid>/fd/<n>`; that works across the
  Flatpak sandbox boundary and needs no privileges.
- **Online.** The title screen runs 30fps/4:3 until you are in a stage (the
  bridge pokes the BSE rate there) — same as the Mac flow. When hosting, the
  server log is `/tmp/smso-server.log`.
- **Display.** 120fps needs a 120Hz output (external display, or an unlocked
  panel). In the Quick Access menu set the frame limit to off/120; Dolphin
  itself runs with VSync off and throttles to `EmulationSpeed = 2.0`.
- **Profiles** are 16:10 (`aspect: "mac"`) for the Deck panel. For a 16:9 TV
  set `"aspect": "tv"` in `launcher/profiles.local.json`.
- Re-running `setup.py` keeps existing config files; `--force` rewrites them
  (with backups).
