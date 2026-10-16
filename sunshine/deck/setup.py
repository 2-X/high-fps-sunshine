#!/usr/bin/env python3
"""One-off Steam Deck setup for the high-fps Sunshine kit. Safe to re-run.

Creates a DEDICATED Dolphin user dir (the stock Dolphin Flatpak's settings and
saves are never written), installs the config kit into it, and points the
launcher at this machine via the gitignored config.local.json /
profiles.local.json:

  ~/.local/share/sms-high-fps/dolphin/      Dolphin user dir (`-u`)
      Config/Dolphin.ini, GFX.ini           Deck-tuned (Vulkan, 2x IR, async shaders)
      Config/GCPadNew.ini, Hotkeys.ini      copied from the stock Dolphin Flatpak
                                            (EmuDeck's Steam Deck mapping), if present
      GameSettings/GMSE01.ini               the repo's Gecko kit

Existing files are left alone unless --force is given (a .bak-<ts> copy is
made first), so controller tweaks and in-game settings survive a re-run.
"""
import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUNSHINE = HERE.parent
REPO = SUNSHINE.parent
KIT = SUNSHINE / "dolphin-config"
LAUNCHER = SUNSHINE / "launcher"

USERDIR = Path.home() / ".local/share/sms-high-fps/dolphin"
STOCK_FLATPAK_CFG = Path.home() / ".var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu"

DOLPHIN_INI = """\
[Analytics]
PermissionAsked = True
Enabled = False
[AutoUpdate]
UpdateTrack =
[General]
HotkeysRequireFocus = False
[Interface]
ConfirmStop = False
UsePanicHandlers = False
OnScreenDisplayMessages = True
PauseOnFocusLost = False
CursorVisibility = 0
[Input]
BackgroundInput = True
[DSP]
DSPThread = True
Backend = Cubeb
EnableJIT = False
[Core]
GFXBackend = Vulkan
CPUThread = True
# Loose SyncGPU: keeps dual-core speed, stops the high-fps FIFO desync
# ("GFX FIFO: Unknown Opcode") — same as the Mac/PC kit.
SyncGPU = True
SyncGpuMaxDistance = 1000000
SyncGpuMinDistance = -1000000
EnableCheats = True
EmulationSpeed = 2.0
AudioPreservePitch = True
AudioStretch = False
DSPHLE = True
SIDevice0 = 6
SIDevice1 = 0
SIDevice2 = 0
SIDevice3 = 0
# MEM1 override: required by the patched build's Gecko code-list relocation
# (and by BSE online). The launcher re-asserts it on every apply.
RAMOverrideEnable = True
MEM1Size = 0x04000000
MEM2Size = 0x08000000
[Display]
Fullscreen = True
RenderToMain = False
"""

GFX_INI = """\
[Enhancements]
ArbitraryMipmapDetection = False
DisableCopyFilter = True
ForceTrueColor = True
[Hacks]
BBoxEnable = False
DeferEFBCopies = True
EFBEmulateFormatChanges = False
EFBScaledCopy = True
EFBToTextureEnable = True
SkipDuplicateXFBs = True
XFBToTextureEnable = True
[Settings]
HiresTextures = False
ShowFPS = True
BackendMultithreading = True
FastDepthCalc = True
# 2x native (1280x1056) — enough for the Deck's 800p panel, cheap on the GPU.
InternalResolution = 2
SaveTextureCacheToState = True
EnableGPUTextureDecoding = True
# Async shader compilation + persistent cache: no cold-cache hitches.
ShaderCompilationMode = 3
WaitForShadersBeforeStarting = False
ShaderCache = True
wideScreenHack = False
[Hardware]
VSync = False
"""

PROFILES = {
    "last": "Deck Offline 120",
    "profiles": [
        {"name": "Deck Offline 120", "mode": "offline", "fps": 120, "fov": 80,
         "aspect": "mac", "ghost": False, "hd_textures": "off",
         "player_name": "Kris Deck", "skin": "mario",
         "qol": {"camera": True, "fludd": True, "savebox": True, "tank": False,
                 "pausejump": True, "gpcam": False}},
        {"name": "Deck Online 120", "mode": "online", "fps": 120, "fov": 90,
         "aspect": "mac", "ghost": False, "hd_textures": "off",
         "player_name": "Kris Deck", "skin": "mario",
         "qol": {"camera": True, "fludd": True, "savebox": True, "tank": False,
                 "pausejump": False, "gpcam": False}},
        {"name": "Deck Solo 120", "mode": "solo", "fps": 120, "fov": 90,
         "aspect": "mac", "ghost": False, "hd_textures": "off",
         "player_name": "Kris Deck", "skin": "mario",
         "qol": {"camera": True, "fludd": True, "savebox": True, "tank": False,
                 "pausejump": False, "gpcam": False}},
    ],
}


def put(dest: Path, *, text=None, src=None, force=False):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        print(f"  [kept]    {dest}")
        return
    if dest.exists():
        shutil.copy2(dest, f"{dest}.bak-{int(time.time())}")
    if src is not None:
        shutil.copy2(src, dest)
    else:
        dest.write_text(text, encoding="utf-8")
    print(f"  [written] {dest}")


# The stock config binds the sticks by raw joystick index (`Axis 2`/`Axis 3` for
# the C-stick). This build's SDL3 sees the Steam virtual pad in kernel order,
# where axis 2 is the left trigger (rests at -32767), so the C-stick reads as
# held left and the camera spins. Named gamepad axes are order-independent.
STICK_AXES = {
    "Main Stick/Up": "Left Y+", "Main Stick/Down": "Left Y-",
    "Main Stick/Left": "Left X-", "Main Stick/Right": "Left X+",
    "C-Stick/Up": "Right Y+", "C-Stick/Down": "Right Y-",
    "C-Stick/Left": "Right X-", "C-Stick/Right": "Right X+",
}


def fix_stick_axes(pad_ini: Path):
    if not pad_ini.exists():
        return
    old = pad_ini.read_text(encoding="utf-8")
    new = re.sub(r"^(Main Stick|C-Stick)/(Up|Down|Left|Right) = .*`Axis \d+[+-]`.*$",
                 lambda m: f"{m[1]}/{m[2]} = `{STICK_AXES[f'{m[1]}/{m[2]}']}`",
                 old, flags=re.M)
    if new != old:
        pad_ini.write_text(new, encoding="utf-8")
        print(f"  [fixed]   {pad_ini} (sticks rebound to named axes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing config files (backups are kept)")
    args = ap.parse_args()

    print(f"Dolphin user dir: {USERDIR}")
    cfg = USERDIR / "Config"
    put(cfg / "Dolphin.ini", text=DOLPHIN_INI, force=args.force)
    put(cfg / "GFX.ini", text=GFX_INI, force=args.force)
    put(USERDIR / "GameSettings" / "GMSE01.ini",
        src=KIT / "GameSettings" / "GMSE01.ini", force=args.force)
    for name in ("GCPadNew.ini", "Hotkeys.ini"):
        src = STOCK_FLATPAK_CFG / name
        if src.exists():
            put(cfg / name, src=src, force=args.force)
        else:
            print(f"  [skip]    no {src} — map the controller in Dolphin")
    fix_stick_axes(cfg / "GCPadNew.ini")

    local = LAUNCHER / "config.local.json"
    data = json.loads(local.read_text()) if local.exists() else {}
    data.setdefault("dolphin_app", str(HERE / "dolphin-deck"))
    data.setdefault("dolphin_user", str(USERDIR))
    data.setdefault("iso_offline", str(Path.home() / "Emulation/roms/gc/Super Mario Sunshine (USA).iso"))
    data.setdefault("iso_dir", str(Path.home() / "Emulation/roms/gc/bsmso-work"))
    local.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  [config]  {local}")
    if "server_addr" not in data:
        print("            (no server_addr yet — online needs the host's IP there)")

    prof = LAUNCHER / "profiles.local.json"
    if prof.exists() and not args.force:
        print(f"  [kept]    {prof}")
    else:
        prof.write_text(json.dumps(PROFILES, indent=2) + "\n")
        print(f"  [written] {prof}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
