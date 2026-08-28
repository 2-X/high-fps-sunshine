"""Static configuration for the Super Mario Sunshine high-FPS launcher.

Everything the launcher needs to know about *where things live* and *what the
knobs mean* is here. No behaviour — just paths, enums, and the QOL catalog.

Two engines are supported, because on this Mac two GMSE01 discs exist:
  - "stock"  : plain pristine-GMSE01.iso + the fpspatch Gecko high-fps bundle.
               FPS is arbitrary (fpspatch generates a bundle per target), FOV is
               a `$FOV N` Gecko code, EmulationSpeed = FPS/60. Offline only.
  - "bse"    : the BSMSO / Better-Sunshine-Engine disc. FPS is a *native* BSE
               setting poked into RAM (set_bse_fps.py / bridge.py) — the engine
               rewrites the stock framerate global every frame, so the fpspatch
               Gecko bundle must NOT be enabled here. FOV is still a `$FOV N`
               Gecko code. Offline OR online (server + bridge).

---- local overrides --------------------------------------------------------
Machine-specific paths can be overridden without touching this file two ways:

  1. sunshine/launcher/config.local.json  (gitignored; created from the .example)
     {
       "iso_offline":  "/path/to/Super Mario Sunshine (USA).rvz",
       "iso_dir":      "/path/to/bsmso-work",
       "dolphin_app":  "/path/to/Dolphin.app",
       "dolphin_user": "/Users/you/Library/Application Support/Dolphin"
     }

  2. Environment variables (highest priority):
       SMS_ISO_OFFLINE   SMS_ISO_DIR   SMS_DOLPHIN_APP   SMS_DOLPHIN_USER

Precedence: env var > config.local.json > default (hardcoded below).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

WIN = sys.platform == "win32"

# ---- repo layout -----------------------------------------------------------
REPO = Path(__file__).resolve().parents[3]          # …/high-fps-dolphin
SUNSHINE = REPO / "sunshine"
LAUNCHER_DIR = SUNSHINE / "launcher"

FPSPATCH = SUNSHINE / "research" / "scripts" / "fpspatch.py"
GECKO = REPO / ".claude" / "skills" / "dolphin-gecko" / "scripts" / "gecko.py"
MAC_ONLINE = SUNSHINE / "bsmso" / "mac-online"
SET_BSE_FPS = MAC_ONLINE / "set_bse_fps.py"
BRIDGE = MAC_ONLINE / "bridge.py"
GHOST = MAC_ONLINE / "ghost_bot.py"
RUN_SERVER = MAC_ONLINE / "run_server.sh"

# Character skins (BSMSO CharacterPack, see mac-online/skins.py). Loaded by
# file path — mac-online is not a package and must stay importable standalone.
def _load_skins_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bsmso_skins", MAC_ONLINE / "skins.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

SKINS_MOD = _load_skins_mod()
SKIN_NAMES = SKINS_MOD.SKIN_NAMES        # ["birdo", ..., "luigi", ..., "yoshi"]
# The dedicated server bundle (gitignored; hand-transferred 2026-08 per
# SYNC-240). Present on BOTH machines now; dotnet ≥8 runs it unchanged.
BUNDLE_SERVER = SUNSHINE / "bsmso" / "bundle-server"
SERVER_DLL = BUNDLE_SERVER / "SMSO.ServerHost.dll"

# ---- local override layer --------------------------------------------------
# Read config.local.json once at import time (file is optional / gitignored).
_LOCAL_JSON = LAUNCHER_DIR / "config.local.json"
_local: dict = {}
if _LOCAL_JSON.exists():
    try:
        _local = json.loads(_LOCAL_JSON.read_text())
    except Exception as _e:
        import warnings
        warnings.warn(f"[smslaunch] Could not parse {_LOCAL_JSON}: {_e}")


def _path(env_var: str, local_key: str, default: Path) -> Path:
    """Resolve a path constant: env > config.local.json > default."""
    if env_var in os.environ:
        return Path(os.environ[env_var]).expanduser()
    if local_key in _local:
        return Path(_local[local_key]).expanduser()
    return default


# ---- Dolphin paths (machine-specific — override via config.local.json) -----
# Defaults are per-platform: the Mac runs the dolphin/ clone's .app bundle and
# keeps user config under Application Support; the PC runs the dolphin-src
# clone's Binary\x64 build and keeps user config under %APPDATA% (see
# [[fludd-aim-invert]]: the live INI on the PC is the APPDATA one).
DOLPHIN_APP = _path(
    "SMS_DOLPHIN_APP",
    "dolphin_app",
    REPO / "dolphin-src" / "Binary" / "x64" / "Dolphin.exe" if WIN
    else REPO / "dolphin" / "build" / "Binaries" / "Dolphin.app",
)
DOLPHIN_USER = _path(
    "SMS_DOLPHIN_USER",
    "dolphin_user",
    Path(os.environ.get("APPDATA", Path.home())) / "Dolphin Emulator" if WIN
    else Path.home() / "Library" / "Application Support" / "Dolphin",
)

# ---- Dolphin user config ---------------------------------------------------
LIVE_INI = DOLPHIN_USER / "GameSettings" / "GMSE01.ini"      # per-game Gecko/Core
DOLPHIN_INI = DOLPHIN_USER / "Config" / "Dolphin.ini"        # global (MEM1 override)
GFX_INI = DOLPHIN_USER / "Config" / "GFX.ini"                # global (wideScreenHack)

# ---- launcher state --------------------------------------------------------
PROFILES_JSON = LAUNCHER_DIR / "profiles.json"
PROFILES_LOCAL_JSON = LAUNCHER_DIR / "profiles.local.json"   # gitignored user copy
LAST_JSON = LAUNCHER_DIR / "last.json"
VENV_PY = (LAUNCHER_DIR / ".venv" / "Scripts" / "python.exe" if WIN
           else LAUNCHER_DIR / ".venv" / "bin" / "python")

# ---- online server ----------------------------------------------------------
# Where the BSMSO dedicated server lives. 127.0.0.1 = this machine hosts (the
# Mac's default: launch() spawns/reuses SMSO.ServerHost locally). Any other
# address = JOIN a remote host over LAN (the PC's default posture: the server
# bundle only exists on the Mac) — launch() then skips the server spawn/health
# checks and points the bridge at it. Override via config.local.json
# ("server_addr") or SMS_SERVER, e.g. the Mac's LAN IP.
SERVER_ADDR = os.environ.get("SMS_SERVER") or _local.get("server_addr") or "127.0.0.1"
SERVER_PORT = 27015                              # TCP + UDP (protocol.py)

# ---- discs (machine-specific — override via config.local.json) -------------
# OFFLINE = the plain Super Mario Sunshine disc (GMSE01) + our stock high-fps
# Gecko kit. ONLINE = the BSMSO / Better Sunshine Engine disc.
ISO_OFFLINE = _path(
    "SMS_ISO_OFFLINE",
    "iso_offline",
    Path(r"C:\Users\krisb\kris-documents\games\dolphin\Super Mario Sunshine (USA).rvz")
    if WIN else Path("/Applications/gamecube/Super Mario Sunshine (USA).rvz"),
)
ISO_DIR = _path(
    "SMS_ISO_DIR",
    "iso_dir",
    Path(r"C:\Users\krisb\kris-documents\games\dolphin\bsmso-work") if WIN
    else Path("/Applications/gamecube/bsmso-work"),
)
ISO_ONLINE = ISO_DIR / "BSMSO-GMSE01.iso"                 # BSE, FPS 30/60/120
ISO_ONLINE_HIGHFPS = ISO_DIR / "BSMSO-GMSE01-highfps.iso"  # fork, adds 240/280/320

# Online (BSE) FPS is a native engine setting — only these values exist.
BSE_FPS_VALUES = [30, 60, 120, 240, 280, 320]
BSE_FORK_ONLY = {240, 280, 320}                  # need the highfps fork disc

# Offline (stock/fpspatch): any multiple of 60, G = FPS/60 an integer >= 2.
STOCK_FPS_SUGGESTED = [120, 180, 240, 360]

# ---- HD textures — optional per-profile tri-state ("off" | "portals" | "full") --
# Three modes for the qashto/razius UHD pack:
#
#   "off"     — HiresTextures disabled; no pack loaded.
#   "portals" — Pruned pack: Delfino M-portal textures (incl. the THP preview
#               movie planes), FLUDD/lives/coins HUD, digits, shine icons,
#               episode-select wordmarks/logos. Vendored in-repo at
#               GMSE01-pruned/; installed as a symlink (~226MB effective).
#   "full"    — Full qashto/razius "SMS 4K 2.0c" pack (~770MB). Lives in
#               Dolphin's 3-char fallback dir (GMS/). We REMOVE our GMSE01
#               symlink so Dolphin falls back to GMS and loads the full pack.
#
# Both discs are GMSE01, so whatever dir is active covers offline AND online.
#
# Shadow mechanic (Dolphin HiresTextures.cpp GetTextureDirectoriesWithGameId):
#   Dolphin uses Load/Textures/<gameid>/ IF it exists, ELSE the 3-char
#   Load/Textures/GMS/. So our GMSE01 symlink SHADOWS GMS entirely — the two
#   packs never stack. "portals" mode installs the GMSE01 link (shadows GMS).
#   "full" mode removes our GMSE01 link so Dolphin falls back to GMS and sees
#   the full pack. "off" leaves whatever is on disk alone and just disables the
#   per-game HiresTextures INI toggle.
#
# HiresTextures/CacheHiresTextures are set per-game in GMSE01.ini
# [Video_Settings] (maps to GFX/Settings) so the toggle is scoped to SMS.
PRUNED_PACK = SUNSHINE / "textures" / "GMSE01-pruned"
HIRES_DEST  = DOLPHIN_USER / "Load" / "Textures" / "GMSE01"
FULL_PACK_DIR = DOLPHIN_USER / "Load" / "Textures" / "GMS"


def _find_full_pack_zip() -> Path | None:
    """Locate the SMS 4K source zip in sunshine/textures/.

    Preference: '(4K)' on Windows, '(1080p)' elsewhere. Falls back to any
    match. Returns None if no zip is present (user must supply it)."""
    candidates = sorted((SUNSHINE / "textures").glob("SMS 4K*.zip"))
    if not candidates:
        return None
    # Prefer the resolution-appropriate variant.
    preferred_tag = "(4K)" if WIN else "(1080p)"
    for z in candidates:
        if preferred_tag in z.name:
            return z
    return candidates[0]   # anything beats nothing


def engine_for(mode: str) -> str:
    """offline -> the stock fpspatch kit; online/solo -> the BSE engine.
    `solo` is the BSE disc booted single-player (no server) — the only way to get
    the BetterSunshineMoveset.kxe moves (Hover Burst, SMO Dive…) offline, since
    that moveset is a Kuribo module that needs the BSE runtime, not a Gecko code."""
    return "bse" if mode in ("online", "solo") else "stock"


def iso_for(mode: str, fps: int) -> Path:
    if mode == "offline":
        return ISO_OFFLINE
    # online + solo both boot the BSE disc (fork disc for the 240/280/320 rates).
    if fps in BSE_FORK_ONLY:
        return ISO_ONLINE_HIGHFPS
    # Clients are distributed ONLY the fork disc, which supports every rate —
    # fall back to it when the plain BSE disc is absent (2026-08-28, John's
    # first launch: 120 -> BSMSO-GMSE01.iso -> FileNotFoundError on every
    # fresh client). Hosts with both discs keep the plain one at <=120.
    return ISO_ONLINE if ISO_ONLINE.exists() else ISO_ONLINE_HIGHFPS


# ---- aspect ----------------------------------------------------------------
# `ratio` = width/height, used to convert the user's horizontal FOV to the
# vertical fovy the $FOV Gecko actually sets. `bse` = native gAspectRatioSetting
# enum; `video` = Dolphin per-game display AspectRatio keys.
# `wshack`  = the Dolphin Widescreen Hack value this aspect needs (global GFX.ini).
#   Dolphin's hack widens the 3D world but is HARDWIRED to 16:9 and ignores the
#   custom display aspect. So 16:9 (`tv`) can ride the hack, but 16:10 (`mac`)
#   CANNOT — the hack would render a 16:9 world stretched into the 16:10 frame
#   (thin/tall). 16:10 instead turns the hack OFF and drives the world aspect
#   from the `$World aspect 16:10` Gecko (codegen.gen_world_aspect); 4:3 needs no
#   widening at all. See [[sunshine-widescreen-2d-fix]].
# `world`   = drive the 3D projection aspect from the Gecko override (hack off)
#   rather than Dolphin's 16:9 hack. Only 16:10 needs it today.
ASPECTS = {
    "mac":  {"label": "16:10 (MBP 16\" fullscreen)", "ratio": 16 / 10, "bse": 2,
             "wshack": "False", "world": True,
             "video": {"AspectRatio": "4", "CustomAspectRatioWidth": "16",
                       "CustomAspectRatioHeight": "10"}},
    "tv":   {"label": "16:9 (external TV/monitor)", "ratio": 16 / 9, "bse": 3,
             "wshack": "True", "world": False,
             "video": {"AspectRatio": "1"}},
    "none": {"label": "4:3 (no widescreen)", "ratio": 4 / 3, "bse": 0,
             "wshack": "False", "world": False,
             "video": {"AspectRatio": "0"}},   # Auto -> native 4:3
}
# aspects that actually apply a widescreen code (offline) — 4:3 applies none.
WIDESCREEN_ASPECTS = {"mac", "tv"}

# ---- code title patterns ---------------------------------------------------
# Titles as they appear in [Gecko] (without the leading '$').
FPS_BUNDLE_TITLE = "SMS {fps}fps bundle (fpspatch, no-ForceOpen)"
FPS_BUNDLE_RE = re.compile(r"^SMS (\d+)fps bundle \(fpspatch, no-ForceOpen\)$")
FOV_TITLE = "FOV {fov}"
FOV_RE = re.compile(r"^FOV (\d+)$")
# BSE variant: the generic FOV code's C_MTXPerspective caller allow-list is
# tuned for the stock disc — under BSMSO some projection consumers (the
# heat-haze shimmer pass) miss it and draw at a mismatched FOV. BSE gets a
# 3-line code that stores fovy at the source (mProjectionFovy @0x80023218).
FOV_TITLE_BSE = "FOV {fov} BSE (mProjectionFovy)"
FOV_BSE_RE = re.compile(r"^FOV (\d+) BSE \(mProjectionFovy\)$")
# Menu d-pad repeat under BSE: reset() sets tick-count delay/interval sized
# for a 30Hz pad ticker; BSE ticks it at the full render rate -> FPS/30x-fast
# scroll. v1 (runtime-guarded on the framerate global) FAILED because reset()
# runs at boot BEFORE the external FPS poke lands, so the guard read 0.5f and
# never scaled — and the config is set once, process-global. v2 is STATIC:
# the launcher generates absolute tick counts for the profile's FPS (no
# runtime guard), generated+enabled per-launch like the FOV code.
MENU_REPEAT_TITLE_BSE = "Menu key-repeat BSE-{fps} v2 (static)"
MENU_REPEAT_BSE_RE = re.compile(r"^Menu key-repeat BSE-(\d+) v2 \(static\)$")

# ---- "Pause while jumping" — a fixed one-line write shared by both discs -----
# Vanilla SMS refuses to open the pause menu mid-air (plays the "nope" buzzer).
# TMarDirector::updateGameMode gates the pause on checkActionThing3(), which is
# false only while the JUMPING status bit is set; NOPing the one gate branch at
# 0x80297AD8 makes the jumping case fall through to STATE_UNK5 (open pause).
# The gate is base main.dol code that BSE does NOT relocate, so this single 04
# write serves offline (stock) AND online (BSE) alike. Framerate-independent.
# Full RE: research/codes/pause-while-jumping-v1.txt.
PAUSE_JUMP_TITLE = "Pause while jumping v1"
PAUSE_JUMP_CODE = "04297AD8 60000000"

# ---- J3D duplicate-entry guard body (see HARDENING_FIXES below) --------------
# Canonical copy + full RE: research/codes/j3d-dup-entry-guard-v1.txt.
# Base main.dol code on both discs; framerate-independent; always on.
J3D_GUARD_TITLE = ("J3D duplicate-entry guard v3 "
                   "(v2 + the four sort-entry bucket inserts)")
J3D_GUARD_CODE = "\n".join([
    # v3 (2026-08-20, freeze #7): the v2 blocks verbatim + the four
    # J3DDrawBuffer SORT-ENTRY push-fronts (0x802EF740/7D0/89C/998) that
    # v1/v2 never hooked - a bucket-level self-link formed via the +0x3C
    # fast path. Canonical + full RE: research/codes/
    # j3d-dup-entry-guard-v3.txt. Same v2.1 discipline: capped chain-walk,
    # 0x80/0x81 pointer validity, fail-open.
    "C22EDC18 00000008",
    "80030034 7C0C0378",
    "39600020 7D6903A6",
    "280C0000 41820028",
    "7C0C2040 4D820020",
    "558B463E 2C0B0080",
    "41800014 2C0B0081",
    "4181000C 818C0004",
    "4200FFD8 00000000",
    "C22ED914 00000008",
    "80030008 7C0C0378",
    "39600020 7D6903A6",
    "280C0000 41820028",
    "7C0C2040 4D820020",
    "558B463E 2C0B0080",
    "41800014 2C0B0081",
    "4181000C 818C0004",
    "4200FFD8 00000000",
    "C22EFA80 00000004",
    "7C002040 4182000C",
    "90040004 48000010",
    "38600001 4E800020",
    "60000000 00000000",
    "C22EFAA0 00000004",
    "7C002040 4182000C",
    "90040004 48000010",
    "38600001 4E800020",
    "60000000 00000000",
    "C22EF740 0000000B",
    "7C0C0378 39600020",
    "7D6903A6 280C0000",
    "41820028 7C0CF840",
    "41820028 558B463E",
    "2C0B0080 41800014",
    "2C0B0081 4181000C",
    "818C0004 4200FFD8",
    "901F0004 48000018",
    "38600001 3D80802E",
    "618CF7DC 7D8903A6",
    "4E800420 00000000",
    "C22EF7D0 0000000B",
    "7C0C0378 39600020",
    "7D6903A6 280C0000",
    "41820028 7C0CF840",
    "41820028 558B463E",
    "2C0B0080 41800014",
    "2C0B0081 4181000C",
    "818C0004 4200FFD8",
    "901F0004 48000018",
    "38600001 3D80802E",
    "618CF7DC 7D8903A6",
    "4E800420 00000000",
    "C22EF89C 0000000B",
    "7CAC2B78 39600020",
    "7D6903A6 280C0000",
    "41820028 7C0C2040",
    "41820028 558B463E",
    "2C0B0080 41800014",
    "2C0B0081 4181000C",
    "818C0004 4200FFD8",
    "90A40004 48000018",
    "38600001 3D80802E",
    "618CF8AC 7D8903A6",
    "4E800420 00000000",
    "C22EF998 0000000B",
    "7C0C0378 39600020",
    "7D6903A6 280C0000",
    "41820028 7C0CF840",
    "41820028 558B463E",
    "2C0B0080 41800014",
    "2C0B0081 4181000C",
    "818C0004 4200FFD8",
    "901F0004 48000018",
    "38600001 3D80802E",
    "618CF9A4 7D8903A6",
    "4E800420 00000000",
])

# ---- QOL toggles (user-facing) ---------------------------------------------
# ONLY genuine quality-of-life / preference codes live here — the things you'd
# actually want to turn on or off (camera, controls, save box, aim). The
# high-fps *correctness* fixes are not toggles; they're applied automatically
# (BASELINE_FIXES below) so the game just works. Each entry resolves to whatever
# full [Gecko] title matches the regex at runtime (None -> unavailable/greyed),
# which survives title drift and avoids the silent "enabled title doesn't match
# a code title -> never ticks" trap.
#   key, label, default-on, {engine: regex-or-None}
QOL_CATALOG = [
    ("camera",     "Camera look-up (+60°)",     True,
     {"stock": r"Camera look-up extension v10", "bse": r"Camera look-up extension v10"}),
    ("fludd",      "FLUDD aim invert",          True,
     {"stock": r"FLUDD Aim Invert v2", "bse": r"FLUDD Aim Invert v3"}),
    # Stock-only: the "Save?" box this reorders is the blue-coin one, and the
    # BSMSO/online build has no blue-coin save dialog (blue coins sync online).
    ("savebox",    "Blue coin save: Continue on top", True,
     {"stock": r"SaveBox: Continue on top", "bse": None}),
    ("tank",       "Tank controls",             False,
     {"stock": r"Tank Controls v8", "bse": r"Tank Controls v8"}),
    # Pause the game mid-jump (vanilla blocks it + buzzes). Same code both discs.
    # Default OFF so it never silently alters the deliberate "vanilla"/no-fix
    # profiles on backfill; the body is auto-installed by launcher.apply().
    ("pausejump",  "Pause while jumping (mid-air)", False,
     {"stock": r"Pause while jumping v1", "bse": r"Pause while jumping v1"}),
]
QOL_KEYS = [k for k, *_ in QOL_CATALOG]

# ---- widescreen (driven by the Aspect dropdown, NOT a QOL toggle) -----------
# Offline (stock disc) needs the projection widescreen Gecko for the chosen aspect
# (`$Widescreen` = 16:9, `$Widescreen 16:10` = generated variant — see codegen)
# PLUS the level-entry wipe fix that stretches the black "curtain" fill to fill
# the frame PLUS the `$Widescreen 2D fix <aspect>` code (codegen.gen_widescreen_2d)
# that repositions the four things the classic code leaves 4:3: the demo wipe/mask
# panes, the shine-select menu masks, its gradient background, and its root pane.
# The 2D fix is COMPLEMENTARY to the wipe fix v2 — v2 scales the TSMSFader solid
# fill (fade transitions); the 2D fix's demo-mask block scales the separate
# TConsoleStr textured wipe curtain + side masks. Keep both.
# Online = BSE renders widescreen natively, so no Gecko is used.
WIDESCREEN_WIPE_FIX = r"Widescreen wipe fix v2"    # aspect-independent curtain fix

# ---- baseline high-fps correctness fixes (always on, ONLINE/BSE only) --------
# The framerate-specific bug fixes the BSE disc needs to run right at high FPS.
# Auto-enabled whenever the matching code exists — never a user toggle. Offline
# doesn't use these: the fpspatch bundle already bakes the same fixes in.
# (noki/petey are intentionally absent — the BSE builds were crashy/unconfirmed;
# this matches the currently shipping working enabled set.)
# `verified` = confirmed correct in-game under BSE. Unverified fixes are NOT
# auto-enabled (quarantine). 2026-08-14 in-game A/B CONFIRMED: `Raw anim-rate
# x0.25` froze water-slide/bonk-star/level-entry-warp anims under BSE (BSE
# natively compensates those rate consumers; quartering them again ~= frozen).
# With it disabled — and Particle parity actually installed for the first
# time (bracket-title fix) — all effects verified correct in-game.
# ---- engine-agnostic hardening (always on, BOTH discs) ----------------------
# J3D duplicate-entry guard: J3D's push-front inserts (J3DMatPacket::
# addShapePacket 0x802EDC18 + three siblings) never check "already the list
# head"; a double entry writes packet->next = packet and the draw walks the
# 1-cycle forever — the Bianco Ep.1 "Road to the Big Windmill" intro freeze,
# five identical live autopsies 2026-08-19 (HANDOFF-NOKI-PERF). The guard
# skips the redundant insert at the corruption site: structurally impossible
# to self-loop, zero behavior change otherwise, engine-independent.
HARDENING_FIXES = [
    # ^-anchored: the BSE-240 Noki v6 title MENTIONS the guard by name ("safe
    # with the J3D duplicate-entry guard — REQUIRES it enabled"), and the
    # unanchored regex resolved to THAT title first (2026-08-27 night: launcher
    # enabled the unsafe noki gate thinking it was the guard, guard silently
    # dropped — the exact freeze pairing the guard exists to prevent).
    ("j3dguard", r"^J3D duplicate-entry guard", True),
]

#   key, regex, verified
BASELINE_FIXES = [
    # The >120 game-speed fix: vanilla's substep scheduler runs the first
    # substep of every frame unconditionally, so above 120 the sim rides the
    # render rate (2x fast at 240 — PC 2026-08-19). Emitted by fpspatch --bse
    # only at fps > 120, and launcher.baseline_titles enforces that scope:
    # NEVER enabled at <=120 even when the title resolves (240 companion
    # installed alongside). The old "harmless-correct at every rate" claim
    # was FALSE — the granularity/anmrate 04s are rate-neutral, but the
    # bundled v9 input latch (thresh 5, a G=3 constant) reads an accumulator
    # remainder that is invariant-0 at 120 (budget == quantum), so it zeroes
    # every trigger edge on TMarDirector-vtable directors: the 2026-08-28
    # BSMSO start-menu lockout (HANDOFF-START-MENU-BUG.md).
    ("substep",   r"Substep 120Hz sim pin BSE",              True),
    ("particle",  r"Particle parity BSE",                    True),
    ("starfix",   r"HUD StarFix v4 BSE",                     True),
    ("wipe",      r"Wipe pace 30Hz gate BSE",                True),
    ("se",        r"SE frame-process 30Hz gate BSE",         True),
    # The two synchronous EFB-peek draw-sync callbacks (Mario occlusion +
    # sun-flare sampler) gated to native 30Hz — the 2026-08-27 offline unlock
    # (Bianco ~170 -> ~315) ported behind the standard BSE guard. Enabled on
    # the offline in-game verdict + guard safety; first BSE in-game pass
    # 2026-08-27 night (Bianco online sat at the ~170 pre-gate ceiling).
    ("peekgate",  r"EFB peek 30Hz gate BSE",                 True),
    # Boid flocking gate ported to BSE 2026-08-28 — Gelato reef red-coin fish
    # outran Mario at 120 (progression blocker). Constant parity-2, guarded.
    ("boid",      r"^Boid flocking 30Hz gate BSE",           True),
    # v6 ONLY (^-anchored, " v6" required: the quarantined v5 "FREEZES" title
    # must never match). Enabled 2026-08-27 night for the first BSE in-game
    # test: with the peek gate live, Bianco online still sat at the pre-gate
    # ~170-177 — the pollution readbacks are the remaining stall (the "no
    # Vulkan win" verdict predates the peek gate). REQUIRES the J3D
    # duplicate-entry guard (HARDENING_FIXES enables it every launch); if
    # Bianco freezes with this on, flip to False and relaunch.
    ("noki",      r"^Noki pollution 30Hz gate BSE-\d+ v6",   True),
    # John's 2026-08-28 A/B: the double/triple-jump chain window is 16 raw
    # ticks consumed at the BSE status-machine cadence (120Hz) — 4x too short
    # at every kit rate. x4 restore at the jumpSlipEvents threshold compare
    # (USA 0x80258D60), guarded. HANDOFF-JUMPCHAIN-BUG.md.
    ("jumpchain", r"^Jump-chain window x4 BSE",              False),
    # Petey's anim-rate site split out of the quarantined blanket family: the
    # v16-era block at 0x800955CC was in-game-confirmed, and Petey runs fast
    # under bare BSE (not natively compensated). The "Raw anim-rate" family
    # itself STAYS quarantined (froze anims 2026-08-14).
    ("petey",     r"^Anim-rate Petey vomit-window BSE",      True),
    ("shimmer",   r"Heat-haze shimmer pace",                 True),
    ("gameclock", r"Game-clock fix v15 BSE",                 True),
    # rate-suffixed scale in the title: x0.25 at 120, x0.125 at 240
    ("anmrate",   r"Raw anim-rate x[\d.]+ fixes BSE",        False),
    ("poink",     r"Poink premature-explosion gate v14 BSE", True),
    # DO NOT wire the "Animal x4" codes here: verdict from the Aug-12 kit chat,
    # re-confirmed 2026-08-14 — the stock-kit x4 assumption is WRONG under BSE
    # (birds overshoot, "flying wayyyy too fast"). Linear bird speeds
    # self-compensate under BSE; only the SQUARED accel term lags (walking
    # birds slow, flying fine) — fixed by the x2 accel-site code below.
    # k = sqrt(FPS/30) in the title: x2 at 120, x2.83 at 240 (fpspatch
    # bird_accel_factor)
    ("birdaccel", r"Bird walk accel x[\d.]+ BSE",             True),
    # Dune Bud spray on the BSMSO disc: vanilla code creates the sand-dust
    # JPA emitter (resource 0x55) and stores scale fields through the result
    # with NO null check -> "Invalid write 0x154/0x158 PC 801d2bcc" every
    # spray. Guard skips the store block when the emitter is null.
    # NOTE 2026-08-14 (late): the original "repacked archive lacks the
    # resource" diagnosis is WRONG — every disc archive is byte-identical to
    # pristine. 0x55 is the actor's own lazy registration of
    # /scene/mapObj/SandBomb.jpa (Gelato stage arcs), skipped when the
    # global once-flag 0x803FD0BD is stale for the current scene's manager.
    # See research/codes/dunebud-dust-v1.txt + mac-online/dunebud_watch.py.
    ("dunebud",   r"DuneBud emitter null-guard BSE",          True),
    # Restores the dust: registry-check instead of once-flag at 0x801d27a4.
    # NEEDS-TEST in Gelato on the BSE disc; flip to True after an in-game
    # pass (keep the null-guard on regardless).
    ("dunebudreg", r"DuneBud dust re-register BSE",           False),
    ("bluecoin",  r"Blue-coin lifetime v6-BSE",              True),
]


def emulation_speed(fps: int) -> float:
    return round(fps / 60.0, 6)


# ---- FOV: users think horizontal, the Gecko sets vertical fovy --------------
import math

FOV_VMIN, FOV_VMAX = 40, 110         # what the $FOV code template can represent
HFOV_MIN, HFOV_MAX = 55, 140         # sane horizontal input range


def hfov_to_vfov(hfov: float, aspect_key: str) -> int:
    """Convert a horizontal FOV (deg) to the integer vertical fovy the $FOV
    Gecko sets, for the profile's display aspect. Clamped to the code's range."""
    ratio = ASPECTS[aspect_key]["ratio"]
    v = math.degrees(2 * math.atan(math.tan(math.radians(hfov) / 2) / ratio))
    return max(FOV_VMIN, min(FOV_VMAX, round(v)))


def vfov_to_hfov(vfov: float, aspect_key: str) -> int:
    ratio = ASPECTS[aspect_key]["ratio"]
    h = math.degrees(2 * math.atan(math.tan(math.radians(vfov) / 2) * ratio))
    return round(h)
