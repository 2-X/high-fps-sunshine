#!/usr/bin/env python3
"""Steam Deck launch driver: configure + boot a profile and stay alive until
Dolphin exits, so Steam treats the whole session as one running game.

    deck_launch.py offline        "Deck Offline 120" (stock disc, fpspatch kit)
    deck_launch.py online         "Deck Online 120"  (BSMSO disc + bridge;
                                  hosts the server here unless server_addr
                                  in config.local.json names another host)
    deck_launch.py solo           "Deck Solo 120"    (BSMSO disc single-player:
                                  BSE moveset, no server / bridge)
    deck_launch.py "<profile>"    any profile name from profiles(.local).json
    deck_launch.py ... --check    preflight only: report what is missing

The Linux counterpart to play120.sh / play240.ps1 — same order of operations:
quit Dolphin -> (online) switch_rate.py regenerates the BSE companion bundle ->
launcher.apply() sets the exact enabled set -> launcher.launch() boots and
starts the bridge -> wait -> stop the helpers.

Discs are found by name so they can simply be dropped into the ROM folder:
  offline: iso_offline from config.local.json, else any *Sunshine* .iso/.rvz/
           .gcm/.ciso in ~/Emulation/roms/gc
  online / solo: BSMSO-GMSE01[-highfps].iso in iso_dir, else in
           ~/Emulation/roms/gc
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUNSHINE = HERE.parent
LAUNCHER = SUNSHINE / "launcher"
ROMS = Path.home() / "Emulation/roms/gc"
LOG_DIR = Path.home() / ".local/share/sms-high-fps/logs"
ALIASES = {"offline": "Deck Offline 120", "online": "Deck Online 120",
           "solo": "Deck Solo 120"}
DISC_EXTS = (".iso", ".rvz", ".gcm", ".ciso", ".gcz")
ONLINE_NAMES = ("BSMSO-GMSE01.iso", "BSMSO-GMSE01-highfps.iso")


def say(msg):
    print(msg, flush=True)


def fail(msg):
    """Report a blocking problem on stdout and, when a display is up, in a
    dialog — a Gaming Mode launch has no terminal to read."""
    say(f"ERROR: {msg}")
    if os.environ.get("SMS_NO_DIALOG") or not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return 1
    # --no-markup: the text holds paths and "<host IP>", which Pango would
    # reject as markup and replace with a bare "An error occurred".
    for cmd in (["zenity", "--error", "--no-markup", "--width=600",
                 "--title=Sunshine high-fps", "--text", msg],
                ["kdialog", "--title", "Sunshine high-fps", "--error", msg]):
        try:
            subprocess.run(cmd, timeout=120)
            break
        except (OSError, subprocess.TimeoutExpired):
            continue
    return 1


def local_config() -> dict:
    p = LAUNCHER / "config.local.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except ValueError:
        return {}


def find_offline_disc(cfg: dict):
    p = Path(cfg.get("iso_offline", "")).expanduser()
    if cfg.get("iso_offline") and p.is_file():
        return p
    if ROMS.is_dir():
        hits = sorted(f for f in ROMS.iterdir()
                      if f.is_file() and f.suffix.lower() in DISC_EXTS
                      and "sunshine" in f.name.lower()
                      and "bsmso" not in f.name.lower())
        if hits:
            return hits[0]
    return None


def find_online_dir(cfg: dict):
    dirs = [Path(cfg["iso_dir"]).expanduser()] if cfg.get("iso_dir") else []
    dirs += [ROMS / "bsmso-work", ROMS]
    for d in dirs:
        if any((d / n).is_file() for n in ONLINE_NAMES):
            return d
    return None


def lan_ip():
    """This machine's LAN address (what joining players put in server_addr).
    connect() on a UDP socket only picks the outgoing interface — nothing is
    sent."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def server_reachable(addr: str, port: int = 27015) -> bool:
    try:
        with socket.create_connection((addr, port), timeout=3):
            return True
    except OSError:
        return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check_only = "--check" in sys.argv
    name = ALIASES.get(args[0], args[0]) if args else ALIASES["offline"]
    cfg = local_config()

    # Resolve machine paths BEFORE importing the launcher: smslaunch.config
    # reads these env overrides once, at import time.
    if not os.environ.get("SMS_ISO_OFFLINE"):
        disc = find_offline_disc(cfg)
        if disc:
            os.environ["SMS_ISO_OFFLINE"] = str(disc)
    if not os.environ.get("SMS_ISO_DIR"):
        d = find_online_dir(cfg)
        if d:
            os.environ["SMS_ISO_DIR"] = str(d)

    sys.path.insert(0, str(LAUNCHER))
    from smslaunch import config as C
    from smslaunch import launcher
    from smslaunch.inieditor import dolphin_running
    from smslaunch.profiles import Store

    # gecko.py / switch_rate.py run as subprocesses and take the user dir from
    # the environment (config.local.json is the launcher's, not theirs).
    os.environ["SMS_DOLPHIN_USER"] = str(C.DOLPHIN_USER)

    prof = Store().get(name)
    if prof is None:
        return fail(f"No profile named '{name}'. Run sunshine/deck/setup.py, "
                    f"or pick one of: {', '.join(Store().names())}")
    online = prof["mode"] == "online"
    say(f"== profile: {prof}")

    # ---- preflight ------------------------------------------------------
    problems = []
    if not C.DOLPHIN_APP.exists():
        problems.append(f"Dolphin wrapper missing: {C.DOLPHIN_APP}")
    built = SUNSHINE.parent / "dolphin" / "build" / "Binaries" / "Dolphin"
    if C.DOLPHIN_APP == HERE / "dolphin-deck" and not built.exists():
        problems.append("Patched Dolphin is not built yet — run "
                        "sunshine/deck/build-dolphin.sh")
    if not C.LIVE_INI.exists():
        problems.append(f"{C.LIVE_INI} missing — run sunshine/deck/setup.py")
    iso = C.iso_for(prof["mode"], prof["fps"])
    if not iso.exists():
        if prof["mode"] == "offline":
            problems.append(
                "Super Mario Sunshine disc image not found.\n\nCopy your own "
                f"NTSC-U (GMSE01) dump into {ROMS} with 'Sunshine' in the file "
                "name (.iso / .rvz), then launch again.")
        else:
            problems.append(
                "BSMSO disc not found.\n\nCopy BSMSO-GMSE01-highfps.iso "
                f"(the online build from the host's kit) into {ROMS / 'bsmso-work'}, "
                "then launch again. A plain Sunshine dump will not work for "
                "online or solo.")
    hosting = online and C.SERVER_ADDR in ("127.0.0.1", "localhost")
    if online:
        if hosting:
            # No server_addr = this Deck hosts: launch() starts the server.
            if not C.SERVER_DLL.exists():
                problems.append(
                    "BSMSO server bundle not found.\n\nTo host on this Deck, "
                    "expand bundle-server.zip (from the Mac/PC kit) to "
                    f"{C.BUNDLE_SERVER}.\n\nTo join another machine's game "
                    "instead, add \"server_addr\": \"<host IP>\" to "
                    f"{LAUNCHER / 'config.local.json'}.")
            if not launcher.find_dotnet():
                problems.append(
                    "dotnet runtime not found (needed to host the server).\n\n"
                    "Install it into ~/.dotnet — see sunshine/deck/README.md.")
        elif not server_reachable(C.SERVER_ADDR, C.SERVER_PORT):
            problems.append(
                f"Online server {C.SERVER_ADDR}:{C.SERVER_PORT} is not "
                "reachable.\n\nCheck that the host is running the BSMSO server "
                "and that this Deck is on the same network / VPN.")
    if problems:
        return fail("\n\n".join(problems))
    say(f"preflight OK — disc: {iso}")
    if hosting:
        say(f"hosting the server on this Deck — others join with server_addr "
            f"{lan_ip() or '<this Deck IP>'} (port {C.SERVER_PORT} TCP+UDP)")
    if check_only:
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    launcher.quit_dolphin(say)

    # ---- online: (re)install the BSE companion kit for this rate ---------
    # The launcher only ENABLES companion codes that already exist in the INI;
    # switch_rate.py is what generates them fresh from fpspatch --bse. apply()
    # below then narrows [Gecko_Enabled] to the launcher's verified set.
    if C.engine_for(prof["mode"]) == "bse":
        bse_aspect = C.ASPECTS[prof["aspect"]]["bse"]
        cmd = [sys.executable, str(C.MAC_ONLINE / "switch_rate.py"),
               "--fps", str(prof["fps"]), "--aspect", str(bse_aspect), "--fov", "0"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        (LOG_DIR / "switch_rate.log").write_text(r.stdout + r.stderr)
        if r.returncode != 0:
            return fail("switch_rate.py failed — see "
                        f"{LOG_DIR / 'switch_rate.log'}")
        say(f"BSE-{prof['fps']} companion kit installed "
            f"(log: {LOG_DIR / 'switch_rate.log'}).")

    launcher.apply(prof, log=say, force=True)
    launcher.launch(prof, log=say)
    if hosting:
        for _ in range(20):               # dotnet cold start can take a while
            if server_reachable("127.0.0.1", C.SERVER_PORT):
                say(f"server listening on port {C.SERVER_PORT}.")
                break
            time.sleep(0.5)
        else:
            say(f"WARNING: server is not listening on port {C.SERVER_PORT} — "
                "see /tmp/smso-server.log")

    # ---- stay alive while the game runs ---------------------------------
    for _ in range(120):                  # launch() already waited; be generous
        if dolphin_running():
            break
        time.sleep(0.5)
    else:
        return fail("Dolphin did not start — run sunshine/deck/dolphin-deck "
                    "from a terminal to see why.")
    try:
        while dolphin_running():
            time.sleep(1)
    except KeyboardInterrupt:
        launcher.quit_dolphin(say)
    finally:
        # Anchored on the interpreter so only the helpers launch() spawned
        # match — a bare `pkill -f bridge.py` also hits any shell or editor
        # whose command line merely mentions the file.
        pats = [r"^[^ ]*python[^ ]* [^ ]*/(bridge|ghost_bot|set_bse_fps)\.py ",
                r"^[^ ]*python[^ ]* -m smslaunch\.verify"]
        if hosting:
            # The server busy-waits a core; never leave it running on battery
            # after the game is closed.
            pats.append(r"^[^ ]*dotnet [^ ]*SMSO\.ServerHost\.dll")
        for pat in pats:
            subprocess.run(["pkill", "-f", pat], capture_output=True)
    say("Dolphin exited — session over.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
