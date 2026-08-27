"""Turn a profile into a configured, running game.

apply()  — generate any missing FPS/FOV codes, set the *exact* [Gecko_Enabled]
           set for the chosen engine, and poke [Core]/[Video_Settings]/MEM1.
           Never runs while Dolphin is alive (INI would be clobbered on quit).
launch() — quit Dolphin, boot the right ISO, then drive FPS the engine's way
           (stock: Gecko bundle already does it; bse: native RAM poke / bridge).

Both take an optional `log` callback so the TUI can stream progress lines.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config as C
from . import codegen
from .inieditor import Ini, dolphin_running

WIN = sys.platform == "win32"
TMP = tempfile.gettempdir()          # /tmp on the Mac, %TEMP% on Windows


def _noop(_msg): pass


def _pkill_f(pattern, log=_noop):
    """Kill processes whose command line contains `pattern` (pkill -f shape)."""
    if not WIN:
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
        return
    ps = ("Get-CimInstance Win32_Process | "
          f"Where-Object {{ $_.CommandLine -like '*{pattern}*' -and "
          f"$_.ProcessId -ne {os.getpid()} }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True)


# ---------------------------------------------------------------- inspection
def _bundle_body(ini: Ini, title: str):
    """The stored hex-pair lines of `title` in [Gecko], or None if absent."""
    span = ini._span("Gecko")
    if not span:
        return None
    cur, out = None, None
    for ln in ini.text[span[0]:span[1]].splitlines():
        if ln.startswith("$"):
            cur = ln[1:].strip()
            if cur == title:
                out = []
        elif cur == title and ln.strip() and not ln.startswith("*"):
            out.append(ln.strip().upper())
    return out



def resolve_qol(ini: Ini, engine: str, qol: dict):
    """-> list of (key, label, wanted, full_title|None, available) for the
    user-facing QOL toggles, resolved for the active engine (offline=stock /
    online=bse). A fix with no matching code for this engine is greyed out."""
    rows = []
    for key, label, _dflt, pats in C.QOL_CATALOG:
        pat = pats.get(engine)
        title = ini.resolve(pat) if pat else None
        rows.append((key, label, bool(qol.get(key)), title, title is not None))
    return rows


def baseline_titles(ini: Ini, engine: str, log=_noop, fps=None) -> list[str]:
    """High-fps correctness codes auto-enabled for ONLINE/BSE. Offline gets its
    equivalents from inside the fpspatch bundle, so returns [].

    Only `verified` fixes are auto-enabled (unverified ports have burned us:
    see the anmrate note in config.BASELINE_FIXES). A verified fix whose regex
    no longer resolves is a LOUD warning, never a silent drop.

    RATE DISAMBIGUATION: since the PC 240 work, an INI can hold BOTH rate
    variants of a companion code ("... BSE-120 ..." and "... BSE-240 ..." —
    they guard on different framerate literals, so only the launched rate's
    copy ever fires, but a bare regex matches both). Prefer the title carrying
    the launched rate's BSE-<fps> tag; else the un-suffixed (120-era) title;
    a residual multi-match is a loud warning."""
    if engine != "bse":
        return []
    titles = ini.titles()
    out = []
    for key, pat, verified in C.BASELINE_FIXES:
        rx = re.compile(pat)
        hits = [t for t in titles if rx.search(t)]
        if len(hits) > 1 and fps is not None:
            tagged = [t for t in hits if f"BSE-{fps}" in t]
            hits = tagged or [t for t in hits if not re.search(r"BSE-\d+", t)] \
                or hits
        if len(hits) > 1:
            log(f"  !! baseline '{key}' (/{pat}/) is AMBIGUOUS at {fps}fps: "
                + ", ".join(hits) + " — enabling none; fix the titles")
            continue
        t = hits[0] if hits else None
        if not verified:
            if t:
                log(f"  ! baseline '{key}' is UNVERIFIED — not auto-enabled "
                    f"(${t})")
            continue
        if t:
            out.append(t)
        elif key == "substep" and (fps is None or fps <= 120):
            pass          # only emitted above 120 — absence is correct there
        else:
            log(f"  !! baseline fix '{key}' (/{pat}/) matched NO [Gecko] code "
                "— the online kit is missing a correctness fix!")
    return out


def widescreen_titles(ini: Ini, engine: str, aspect: str) -> list[str]:
    """Widescreen codes implied by the Aspect dropdown. Offline = the projection
    Gecko for THIS aspect (16:9 `$Widescreen` / 16:10 `$Widescreen 16:10`) + the
    level-entry curtain/wipe fix; online = BSE-native (none)."""
    if engine != "stock" or aspect not in C.WIDESCREEN_ASPECTS:
        return []                            # online = BSE native; 4:3 = no code
    out = []
    proj = codegen.WS_TITLE.get(aspect)      # exact title for this aspect
    if proj and proj in ini.titles():
        out.append(proj)
    # 3D world projection aspect: aspects Dolphin's 16:9-only hack can't serve
    # (16:10) drive it from the C_MTXPerspective override instead. See codegen.
    if C.ASPECTS[aspect].get("world"):
        world = codegen.WORLD_ASPECT_TITLE.get(aspect)
        if world and world in ini.titles():
            out.append(world)
    twod = codegen.WS2D_TITLE.get(aspect)    # the 4:3-leftovers fix (wipe/menu/grad/pane)
    if twod and twod in ini.titles():
        out.append(twod)
    wipe = ini.resolve(C.WIDESCREEN_WIPE_FIX)
    if wipe:
        out.append(wipe)
    return out


def vfov_of(profile: dict):
    """The vertical fovy the $FOV code sets for this profile's hFOV + aspect, or
    None when FOV is left blank (no FOV code — keep the game's stock FOV)."""
    if profile.get("fov") in (None, ""):
        return None
    return C.hfov_to_vfov(profile["fov"], profile["aspect"])


def enabled_set_for(ini: Ini, profile: dict, log=_noop) -> list[str]:
    """The full [Gecko_Enabled] title list this profile wants:
      offline: FOV + fpspatch bundle + on QOL (timing fixes are IN the bundle)
      online : FOV + always-on BSE baseline fixes + on QOL
    """
    engine = C.engine_for(profile["mode"])
    titles: list[str] = []
    vfov = vfov_of(profile)
    if vfov is not None:                               # blank FOV = keep stock
        # BSE gets the mProjectionFovy variant (the generic template's caller
        # filter misses the shimmer pass under BSMSO -> mismatched FOV).
        fov_tmpl = C.FOV_TITLE_BSE if engine == "bse" else C.FOV_TITLE
        titles.append(fov_tmpl.format(fov=vfov))
    if engine == "stock" and profile["fps"] >= 120:   # 60 = native, no bundle
        titles.append(C.FPS_BUNDLE_TITLE.format(fps=profile["fps"]))
    if engine == "bse" and profile["fps"] != 30:      # 30 = native tick counts
        titles.append(C.MENU_REPEAT_TITLE_BSE.format(fps=profile["fps"]))
    titles += baseline_titles(ini, engine, log, fps=profile["fps"])
    for _key, pat, _v in C.HARDENING_FIXES:   # engine-agnostic, always on
        t = ini.resolve(pat)
        if t:
            titles.append(t)
        else:
            log(f"  !! hardening fix /{pat}/ matched NO [Gecko] code — "
                "install it (see config.HARDENING_FIXES)")
    titles += widescreen_titles(ini, engine, profile["aspect"])  # aspect dropdown
    for _key, _label, wanted, title, avail in resolve_qol(ini, engine, profile["qol"]):
        if wanted and avail:
            titles.append(title)
    seen, out = set(), []       # de-dupe, keep order
    for t in titles:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def plan(profile: dict) -> dict:
    """Read-only preview for the UI: what exists, what will be generated."""
    ini = Ini(C.LIVE_INI)
    engine = C.engine_for(profile["mode"])
    vfov = vfov_of(profile)
    have_fov = (codegen.existing_fov_bse_codes(ini) if engine == "bse"
                else codegen.existing_fov_codes(ini))
    have_fps = codegen.existing_fps_bundles(ini)
    return {
        "engine": engine,
        "iso": C.iso_for(profile["mode"], profile["fps"]),
        "emulation_speed": C.emulation_speed(profile["fps"]),
        "vfov": vfov,
        "have_fov": have_fov,
        "fov_needed": vfov is not None and vfov not in have_fov,
        "have_fps": have_fps,
        "fps_needed": engine == "stock" and profile["fps"] >= 120
                      and profile["fps"] not in have_fps,
        "fps_native": engine == "stock" and profile["fps"] < 120,   # 60 = native
        "fps_supported": engine == "stock" or profile["fps"] in C.BSE_FPS_VALUES,
        "enabled": enabled_set_for(ini, profile),
        "baseline": baseline_titles(ini, engine, fps=profile["fps"]),
        "widescreen": widescreen_titles(ini, engine, profile["aspect"]),
        "qol_rows": resolve_qol(ini, engine, profile["qol"]),
    }


# ------------------------------------------------------------------- helpers
def quit_dolphin(log=_noop):
    if not dolphin_running():
        return
    log("Quitting Dolphin (so it can't clobber the INI on exit)…")
    if WIN:
        subprocess.run(["taskkill", "/IM", "Dolphin.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-x", "Dolphin"])
    for _ in range(20):
        if not dolphin_running():
            break
        time.sleep(1)
    if dolphin_running():
        log("Dolphin still up — force killing.")
        if WIN:
            subprocess.run(["taskkill", "/F", "/IM", "Dolphin.exe"],
                           capture_output=True)
        else:
            subprocess.run(["pkill", "-9", "-x", "Dolphin"])
        time.sleep(2)


def _set_dolphin_mem1(enable: bool, log=_noop):
    """RAMOverride for the BSE puppet heap (needs 64MB MEM1). Edits global
    Dolphin.ini [Core]; applies at boot, so do it while Dolphin is quit."""
    if not C.DOLPHIN_INI.exists():
        return
    ini = Ini(C.DOLPHIN_INI)   # reuse the section plumbing
    if enable:
        ini.set_core("RAMOverrideEnable", "True")
        ini.set_core("MEM1Size", "0x04000000")
        ini.set_core("MEM2Size", "0x08000000")
    else:
        ini.set_core("RAMOverrideEnable", "False")
    ini.save(force=True)   # Dolphin already quit by caller
    log(f"MEM1 override {'ON (64MB)' if enable else 'off'}.")


def _set_wshack(value: str, log=_noop):
    """Set Dolphin's global Widescreen Hack (GFX.ini [Settings] wideScreenHack).
    16:9 (`tv`) rides the hack for its 3D widening; 16:10/4:3 turn it OFF (16:10
    drives the world from the `$World aspect` Gecko instead — the hack is
    16:9-only). Applies at boot, so write it while Dolphin is quit."""
    if not C.GFX_INI.exists():
        return
    import re
    text = C.GFX_INI.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    sect = next((i for i, l in enumerate(lines)
                 if l.strip().lower() == "[settings]"), None)
    if sect is None:
        lines += ["[Settings]", f"wideScreenHack = {value}"]
    else:
        end = next((j for j in range(sect + 1, len(lines))
                    if re.match(r"^\[.+\]\s*$", lines[j].strip())), len(lines))
        pat = re.compile(r"^\s*wideScreenHack\s*=\s*(.*)$")
        for k in range(sect + 1, end):
            if pat.match(lines[k]):
                if lines[k].split("=", 1)[1].strip() == value:
                    return                          # already correct
                lines[k] = f"wideScreenHack = {value}"
                break
        else:
            lines.insert(end, f"wideScreenHack = {value}")
    C.GFX_INI.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"Dolphin Widescreen Hack -> {value} (3D world = "
        f"{'Dolphin 16:9 hack' if value == 'True' else 'Gecko/native'}).")


# --------------------------------------------------------------------- apply
def apply(profile: dict, *, log=_noop, force=False):
    """Configure the INI to satisfy `profile`. Returns nothing; raises on error."""
    quit_dolphin(log)
    ini = Ini(C.LIVE_INI)
    engine = C.engine_for(profile["mode"])

    # 1a. offline only: generate the fpspatch FPS bundle if it's never been built.
    #     60fps is the console's native rate — no bundle, just EmulationSpeed 1.0.
    if engine == "stock" and profile["fps"] >= 120:
        # ALWAYS regenerate and compare: fpspatch is the source of truth, and a
        # stale stored bundle bites silently (2026-08-14: a reused bundle still
        # carried the superseded per-site SE gates and lacked the SE30/shimmer
        # fixes). Regeneration is fast; replace on any difference.
        title, code = codegen.gen_fps_bundle(profile["fps"])
        stored = _bundle_body(ini, title)
        fresh = [ln.upper() for ln in code.splitlines() if ln.strip()]
        if stored is None:
            log(f"Generating {profile['fps']}fps bundle (fpspatch)…")
            ini.add_code(title, code)
            log(f"  + ${title}")
        elif stored != fresh:
            log(f"{profile['fps']}fps bundle is STALE ({len(stored)} lines vs "
                f"{len(fresh)} fresh) — regenerating from fpspatch.")
            ini.add_code(title, code)          # replace=True swaps the body
        else:
            log(f"Reusing {profile['fps']}fps bundle (verified current).")
    elif engine == "stock":
        log(f"{profile['fps']}fps = native rate — no high-fps bundle needed.")

    # 1a2. offline only: build the widescreen Gecko for this aspect if missing
    #      (16:9 = the shipped $Widescreen; 16:10 = the generated variant).
    if engine == "stock":
        ws_title = codegen.WS_TITLE.get(profile["aspect"])
        if ws_title and ws_title not in ini.titles():
            title, code = codegen.gen_widescreen(profile["aspect"])
            ini.add_code(title, code)
            log(f"Generating ${title} (aspect widescreen)…  + ${title}")
        # the 3D world projection aspect override (drives the world when Dolphin's
        # 16:9-only Widescreen Hack can't — i.e. 16:10). Regenerate+replace always:
        # a hand-assembled C2 is cheap to rebuild and stale bodies bite silently.
        if C.ASPECTS[profile["aspect"]].get("world"):
            title, code = codegen.gen_world_aspect(profile["aspect"])
            ini.add_code(title, code)          # replace=True refreshes the body
            log(f"Generating ${title} (3D world aspect override)…  + ${title}")
        # the 2D-leftovers fix (level-wipe curtain + masks, shine-select menu
        # masks/gradient/root pane) that the classic $Widescreen leaves at 4:3.
        # Drop any superseded v1 body first so the vN title bump actually
        # deploys (generate-if-missing would otherwise leave the stale v1 code
        # in [Gecko]; set_enabled already keeps v1 out of [Gecko_Enabled]).
        for stale in codegen.WS2D_TITLE_STALE:
            if stale in ini.titles():
                ini.remove_code(stale)
                log(f"Removed stale ${stale} (superseded by v2 calibration).")
        ws2d_title = codegen.WS2D_TITLE.get(profile["aspect"])
        if ws2d_title and ws2d_title not in ini.titles():
            title, code = codegen.gen_widescreen_2d(profile["aspect"])
            ini.add_code(title, code)
            log(f"Generating ${title} (widescreen 2D leftovers)…  + ${title}")

    # 1a3. QOL "Pause while jumping": a fixed one-line write shared by both discs
    #      (the air-pause gate at 0x80297AD8 is base-DOL code, identical offline/
    #      BSE). Ensure the body exists so the toggle can enable it — it is never
    #      auto-enabled here, only when the profile's QOL flag is on (step 2).
    if C.PAUSE_JUMP_TITLE not in ini.titles():
        ini.add_code(C.PAUSE_JUMP_TITLE, C.PAUSE_JUMP_CODE)
        log(f"Installing ${C.PAUSE_JUMP_TITLE} (pause mid-air)…")

    # 1a4. ALWAYS-ON hardening: the J3D duplicate-entry guard (both discs).
    #      Ensure the body exists; HARDENING_FIXES enables it every launch.
    if C.J3D_GUARD_TITLE not in ini.titles():
        for stale in [t for t in ini.titles()
                      if t.startswith("J3D duplicate-entry guard") and
                      t != C.J3D_GUARD_TITLE]:
            ini.remove_code(stale)
            log(f"Removed stale ${stale} (superseded).")
        ini.add_code(C.J3D_GUARD_TITLE, C.J3D_GUARD_CODE)
        log(f"Installing ${C.J3D_GUARD_TITLE}…")

    # 1b. generate the FOV code (at the vertical fovy for this hFOV+aspect), or
    #     skip entirely when FOV is left blank (keep the game's stock FOV) -------
    vfov = vfov_of(profile)
    if vfov is not None and abs(vfov - 45) <= 2:
        import math
        ratio = C.ASPECTS[profile["aspect"]]["ratio"]
        classic = round(math.degrees(2 * math.atan(
            math.tan(math.radians(69 / 2)) * ratio)))
        log(f"  ! hFOV {profile['fov']}° → vertical {vfov}° ≈ the game's STOCK "
            f"FOV (~45°) — you won't see a change. For the classic wide "
            f"'$FOV 69' feel enter {classic}.")
    if vfov is None:
        log("FOV left blank — no FOV code (keeping the game's stock FOV).")
    elif engine == "bse":
        if vfov not in codegen.existing_fov_bse_codes(ini):
            log(f"Generating BSE $FOV {vfov} (mProjectionFovy; "
                f"hFOV {profile['fov']}° @ {profile['aspect']})…")
            title, code = codegen.gen_fov_bse(vfov)
            ini.add_code(title, code)
            log(f"  + ${title}")
        else:
            log(f"Reusing existing BSE $FOV {vfov} (hFOV {profile['fov']}°).")
    else:
        have_fov = codegen.existing_fov_codes(ini)
        if vfov not in have_fov:
            log(f"Generating $FOV {vfov} (hFOV {profile['fov']}° @ {profile['aspect']})…")
            title, code = codegen.gen_fov(vfov)
            ini.add_code(title, code)
            log(f"  + ${title}")
        else:
            log(f"Reusing existing $FOV {vfov} (hFOV {profile['fov']}°).")

    # 1c. BSE only: static menu key-repeat counts for this FPS (see codegen) ----
    if engine == "bse" and profile["fps"] != 30:
        mr_title, mr_code = codegen.gen_menu_repeat_bse(profile["fps"])
        if mr_title not in ini.titles():
            ini.add_code(mr_title, mr_code)
            log(f"Generating ${mr_title} (static menu d-pad repeat)…")

    # 2. exact enabled set: FOV + always-on baseline fixes + QOL toggles --------
    enabled = enabled_set_for(ini, profile, log)
    # Only enable titles that actually exist (a QOL/FOV we just added does).
    present = set(ini.titles())
    missing = [t for t in enabled if t not in present]
    enabled = [t for t in enabled if t in present]
    from .inieditor import dolphin_name
    prev = {dolphin_name(t) for t in ini.enabled()}
    ini.set_enabled(enabled)
    log(f"Enabled {len(enabled)} codes: " + ", ".join("$" + t.split(" (")[0]
                                                       for t in enabled))
    if missing:
        log("  !! skipped, not in [Gecko]: " + ", ".join(missing))
    # Surface enabled-set drift vs the previous launch — a silently-grown or
    # shrunk kit is exactly how this launcher once shipped an untested fix.
    now = {dolphin_name(t) for t in enabled}
    for t in sorted(now - prev):
        log(f"  + newly enabled vs last launch: ${t}")
    for t in sorted(prev - now):
        log(f"  - no longer enabled vs last launch: ${t}")

    # 3. Core: cheats + emulation speed + audio ---------------------------------
    ini.set_core("EnableCheats", "True")
    ini.set_core("EmulationSpeed", C.emulation_speed(profile["fps"]))
    ini.set_core("AudioPreservePitch", "True")

    # 4. display aspect + HD-texture toggle (tri-state: "off"/"portals"/"full") -
    #    Both go in [Video_Settings] (one rewrite). "portals" installs the GMSE01
    #    symlink (shadowing GMS) and enables HiresTextures. "full" removes that
    #    symlink so Dolphin falls back to Load/Textures/GMS (the full 4K pack,
    #    extracted on first use). "off" disables HiresTextures without removing
    #    anything. See hdtextures.py for the full shadow-mechanic explanation.
    from . import hdtextures
    video = dict(C.ASPECTS[profile["aspect"]]["video"])
    video.update(hdtextures.apply(profile.get("hd_textures", "off"), log=log))
    ini.set_video(video)

    # 4b. Dolphin Widescreen Hack (global GFX.ini). BSE renders widescreen
    #     natively so its hack is always OFF (else double-widen); offline follows
    #     the aspect policy: 16:9 rides the hack, 16:10/4:3 turn it off.
    wshack = "False" if engine == "bse" else C.ASPECTS[profile["aspect"]]["wshack"]
    _set_wshack(wshack, log)

    ini.save(force=force)
    log(f"Wrote {C.LIVE_INI.name} (backup .bak). "
        f"EmulationSpeed={C.emulation_speed(profile['fps'])}.")

    # 5. MEM1 = 64MB, ALWAYS. Two independent reasons need the expanded arena:
    #    - online: BSE's remote-puppet heap lives in the extended MEM1 arena.
    #    - both:  the custom build's Gecko code-cap lift relocates a large
    #      codelist (>~406 lines) to 0x81800000 = 0x80000000 + MEM1_SIZE_RETAIL,
    #      and caps it at min(0x80000000+mem1_size, 0x81810000). With retail 24MB
    #      MEM1 that window is ZERO bytes, so every code past the base cap
    #      silently drops — which killed the offline bundle's timestep blocks
    #      (game ran 60fps at 2x). The offline codelist is ~442 lines, so it
    #      MUST have the expanded arena. (Harmless for the stock disc: the game
    #      only uses the retail 24MB; the extra RAM just backs the codelist.)
    _set_dolphin_mem1(True, log)


# -------------------------------------------------------------------- launch
def _spawn(cmd, cwd, logpath):
    lf = open(logpath, "ab")
    return subprocess.Popen(cmd, cwd=str(cwd), stdout=lf, stderr=lf,
                            start_new_session=True)


def _spawn_verify(profile: dict, log=_noop):
    """Detached post-launch verification (BSE modes): proves every enabled
    Gecko code actually installed and the native FPS poke landed. Without
    this, a silently-dead code list looks identical to a working one."""
    vlog = os.path.join(TMP, "sms-verify.log")
    _spawn([sys.executable, "-m", "smslaunch.verify",
            "--fps", str(profile["fps"])], C.LAUNCHER_DIR, vlog)
    log(f"Post-launch verify scheduled (~30s) — result: {vlog}")


def launch(profile: dict, *, log=_noop):
    """Boot the game for `profile`. Assumes apply() already ran."""
    iso = C.iso_for(profile["mode"], profile["fps"])
    if not iso.exists():
        raise FileNotFoundError(f"ISO not found: {iso}")
    quit_dolphin(log)
    # Always clear helpers from the PREVIOUS session. A lingering ghost_bot
    # otherwise reconnects even when the ghost box is unticked (and a stale
    # bridge would double-poke). They are respawned below only if wanted.
    _pkill_f("ghost_bot.py")
    _pkill_f("bridge.py")

    log(f"Booting {iso.name} …")
    if WIN:
        subprocess.Popen([str(C.DOLPHIN_APP), "-e", str(iso)])
    else:
        subprocess.run(["open", "-a", str(C.DOLPHIN_APP), "--args", "-e", str(iso)])

    # OFFLINE = the stock SMS disc: the fpspatch Gecko bundle + EmulationSpeed
    # drive the framerate. Nothing to poke, no server.
    if profile["mode"] == "offline":
        log("Offline (stock disc): fpspatch bundle + EmulationSpeed drive the "
            "framerate. Ready — pick your save and play.")
        return

    # Both BSE modes below need the native FPS/aspect poked into RAM.
    bse_aspect = C.ASPECTS[profile["aspect"]]["bse"]

    # SOLO = the BSE disc booted single-player: full BetterSunshineMoveset (Hover
    # Burst, SMO Dive…) loads from its Kuribo module, but NO server/bridge/ghost.
    # BSE boots at mFPSValue=0 (30fps) → 30×EmulationSpeed = 2x-speed 60fps until
    # something writes the FPS enum, so poke it once via the no-stage one-shot.
    if profile["mode"] == "solo":
        log(f"Solo BSE moveset: poking native FPS={profile['fps']} / "
            f"aspect={bse_aspect} (no server)…")
        _spawn([sys.executable, str(C.SET_BSE_FPS), "--fps", str(profile["fps"]),
                "--aspect", str(bse_aspect)], C.MAC_ONLINE,
               os.path.join(TMP, "set_bse_fps.log"))
        log("Full moveset (Hover Burst, SMO Dive, Rocket/Side Dive…) loads from "
            "BetterSunshineMoveset.kxe. FPS poke retries until BSE registers "
            f"(~seconds into boot) — log: {os.path.join(TMP, 'set_bse_fps.log')}. "
            "Play solo.")
        _spawn_verify(profile, log)
        return

    # ONLINE = the BSE disc: framerate/aspect are native settings poked into RAM,
    # plus the server + bridge (+ ghost). The bridge re-pokes FPS/aspect each loop.
    server = C.SERVER_ADDR
    if server in ("127.0.0.1", "localhost"):
        # This machine hosts. A long-lived server degrades (busy-wait spin
        # accumulates with every connect/disconnect; 300-600% CPU seen after
        # hours up) and its world-sync reheal then wedges the client
        # GUEST-side on stage entry — the 2026-08-14 "freeze in Delfino / at
        # Wiggler" class. Reuse only a healthy server; restart a spun-up one.
        if WIN:
            # Windows hosting (Route A, SYNC-240 2026-08-19): the bundle was
            # hand-transferred from the Mac; dotnet ≥8 runs it unchanged.
            if not C.SERVER_DLL.exists():
                raise RuntimeError(
                    f"No server bundle at {C.BUNDLE_SERVER} — expand "
                    "bundle-server.zip there (SYNC-240 2026-08-19), or set "
                    "server_addr/SMS_SERVER to the host's LAN IP to join.")
            q = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Process | Where-Object "
                 "{ $_.CommandLine -like '*SMSO.ServerHost*' }).ProcessId"],
                capture_output=True, text=True).stdout.split()
            if q:
                log(f"Server already running (pid {q[0]}).")
            else:
                log("Starting BSMSO server (dotnet SMSO.ServerHost.dll)…")
                lf = open(os.path.join(TMP, "smso-server.log"), "ab")
                p = subprocess.Popen(["dotnet", str(C.SERVER_DLL)],
                                     cwd=str(C.BUNDLE_SERVER),
                                     stdout=lf, stderr=lf,
                                     creationflags=0x00004000)  # BELOW_NORMAL
                log(f"Server pid {p.pid}, deprioritized (below-normal) so "
                    "Dolphin keeps its FPS. First run: allow the Windows "
                    "Firewall prompt (27015 TCP+UDP inbound) or the Mac "
                    "cannot join.")
                time.sleep(3)
        else:
            sp = subprocess.run(["pgrep", "-f", "SMSO.ServerHost"],
                                capture_output=True, text=True).stdout.split()
            if sp:
                cpu = subprocess.run(["ps", "-p", sp[0], "-o", "pcpu="],
                                     capture_output=True, text=True).stdout.strip()
                if float(cpu or 0) > 150:
                    log(f"Server degraded ({cpu.strip()}% CPU) — restarting it fresh.")
                    subprocess.run(["pkill", "-f", "SMSO.ServerHost"])
                    time.sleep(2)
                    sp = []
                else:
                    log(f"Server already running (healthy, {cpu.strip()}% CPU).")
            if not sp:
                log("Starting BSMSO server…")
                _spawn(["/bin/zsh", str(C.RUN_SERVER)], C.MAC_ONLINE,
                       os.path.join(TMP, "smso-server.log"))
                time.sleep(3)
            # The server busy-waits (600%+ CPU with clients attached) and starves
            # Dolphin below the target FPS. Until the spin is fixed at source, pin
            # it to lowest priority so the emulator always wins the CPU fight.
            pids = subprocess.run(["pgrep", "-f", "SMSO.ServerHost"],
                                  capture_output=True, text=True).stdout.split()
            for pid in pids:
                subprocess.run(["renice", "19", "-p", pid], capture_output=True)
            if pids:
                log("Server deprioritized (nice 19) so Dolphin keeps its FPS.")
        time.sleep(1)
    else:
        log(f"Joining remote server at {server}:{C.SERVER_PORT} (no local "
            f"server spawn — make sure the host machine's game is up).")
    log(f"Starting bridge (name={profile['player_name']}, fps={profile['fps']})…")
    _spawn([sys.executable, str(C.BRIDGE), "--server", server,
            "--name", profile["player_name"], "--fps", str(profile["fps"]),
            "--aspect", str(bse_aspect)], C.MAC_ONLINE,
           os.path.join(TMP, "bridge.log"))
    if profile["ghost"]:
        log("Starting ghost bot…")
        _spawn([sys.executable, str(C.GHOST), "--server", server,
                "--name", "Ghost"], C.MAC_ONLINE, os.path.join(TMP, "ghost.log"))
    log("Online up. Enter a stage (Delfino) — bridge attaches once the session "
        f"is active. Logs: {os.path.join(TMP, 'bridge.log')}, "
        f"{os.path.join(TMP, 'smso-server.log')}.")
    _spawn_verify(profile, log)
