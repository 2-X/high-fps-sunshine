"""Install / uninstall HD texture packs (pruned portals or full SMS 4K 2.0c).

Three modes correspond to the profile's ``hd_textures`` field:

  "off"     — HiresTextures disabled. No files touched.
  "portals" — Pruned pack (Delfino M-portals, FLUDD/lives HUD, shine icons,
               episode-select wordmarks; ~226MB). Vendored in-repo at
               sunshine/textures/GMSE01-pruned/. Installed as a symlink from
               Load/Textures/GMSE01 → the repo copy. The GMSE01 dir shadows any
               GMS dir (see config.py shadow mechanic note), so only the pruned
               pack is active.
  "full"    — Full qashto/razius "SMS 4K 2.0c" pack (~770MB). Lives in Dolphin's
               3-char fallback dir Load/Textures/GMS/. We REMOVE our GMSE01
               symlink so Dolphin falls back to GMS and sees the full pack. The
               source zip (sunshine/textures/SMS 4K*.zip, gitignored) is extracted
               on first use; this is a one-time ~770MB operation.

Dolphin loads hires textures from Load/Textures/<gameid>/ if it exists, else the
3-char Load/Textures/GMS/ (HiresTextures.cpp GetTextureDirectoriesWithGameId).
Both the offline (stock) and online (BSMSO) discs are GMSE01, so one install
covers both. We never clobber a real user-created directory.

Enabling/disabling is also a per-game GMSE01.ini [Video_Settings] HiresTextures
toggle, returned from apply() for the caller (launcher.apply) to write alongside
the aspect keys.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

from . import config as C


def _noop(_m):
    pass


# The per-game GFX keys that turn the pack on/off. Live in GMSE01.ini
# [Video_Settings] (maps to GFX/Settings), scoping hires textures to SMS.
def video_settings(on: bool) -> dict:
    v = "True" if on else "False"
    return {"HiresTextures": v, "CacheHiresTextures": v}


def _is_link(dest: Path) -> bool:
    """Symlink on any OS, or an NTFS junction on Windows. Junctions are the
    unprivileged Windows equivalent (plain symlinks need admin/Developer Mode);
    Dolphin follows both identically. Python 3.12+ has os.path.isjunction."""
    if dest.is_symlink():
        return True
    isj = getattr(os.path, "isjunction", None)
    return bool(isj and isj(dest))


def status() -> str:
    """'linked' | 'linked-elsewhere' | 'realdir' | 'missing' — what currently
    sits at Load/Textures/GMSE01."""
    dest = C.HIRES_DEST
    if _is_link(dest):
        try:
            return "linked" if dest.resolve() == C.PRUNED_PACK.resolve() \
                   else "linked-elsewhere"
        except OSError:
            return "linked-elsewhere"
    if dest.exists():
        return "realdir"
    return "missing"


def ensure_installed(*, log=_noop) -> None:
    """Make Load/Textures/GMSE01 point at the vendored pruned pack. Idempotent;
    refuses to touch a real (non-symlink) directory the user may have put there."""
    if not C.PRUNED_PACK.is_dir():
        raise FileNotFoundError(f"pruned texture pack missing: {C.PRUNED_PACK}")
    dest = C.HIRES_DEST
    st = status()
    if st == "linked":
        log(f"HD texture pack already installed ({dest.name} → GMSE01-pruned).")
        return
    if st == "realdir":
        # Don't delete a real folder the user populated by hand.
        raise FileExistsError(
            f"{dest} is a real directory (not our symlink) — leaving it alone. "
            "Move/remove it yourself if you want the launcher to manage it.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _is_link(dest):                          # stale/wrong link — replace it
        dest.unlink()
    try:
        os.symlink(C.PRUNED_PACK, dest)
    except OSError:
        # Windows: plain symlinks need admin/Developer Mode. Fall back to an
        # NTFS junction — unprivileged, and Dolphin follows it identically.
        if os.name != "nt":
            raise
        import subprocess
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(dest),
                            str(C.PRUNED_PACK.resolve())],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise OSError(f"junction fallback failed: {r.stderr.strip()}")
    n = sum(1 for _ in C.PRUNED_PACK.rglob("*.dds"))
    log(f"Installed HD texture pack: {dest} → GMSE01-pruned ({n} .dds).")


def full_status() -> str:
    """'present' if Load/Textures/GMS exists and has content, else 'missing'."""
    d = C.FULL_PACK_DIR
    if d.is_dir() and any(d.iterdir()):
        return "present"
    return "missing"


def ensure_full_installed(*, log=_noop) -> None:
    """Ensure the full SMS 4K 2.0c pack is extracted to Load/Textures/GMS/.

    If the directory already has content, this is a no-op. Otherwise the source
    zip is located via config._find_full_pack_zip(); if no zip is available a
    FileNotFoundError is raised with clear instructions. Extraction is a one-time
    ~770MB operation: only members under .../Load/Textures/GMS/ are extracted,
    stripping everything up to and including that marker so files land directly
    in FULL_PACK_DIR. Directory entries and path-traversal attempts are skipped."""
    if full_status() == "present":
        log(f"Full HD pack already present ({C.FULL_PACK_DIR}).")
        return
    zip_path = C._find_full_pack_zip()
    if zip_path is None:
        raise FileNotFoundError(
            "Full SMS 4K 2.0c pack not found. Provide it one of two ways:\n"
            f"  1. Place the source zip in: {C.SUNSHINE / 'textures'}/\n"
            f"     (e.g. 'SMS 4K Texture Pack 2.0c (1080p).zip')\n"
            f"  2. Extract the pack yourself to: {C.FULL_PACK_DIR}\n"
            f"     (inner path must be Load/Textures/GMS/ inside the zip)")
    log(f"Extracting full HD pack from {zip_path.name} — one-time ~770MB operation…")
    # The zip inner layout is:
    #   <pack name>/Load/Textures/GMS/<textures>
    # We extract only members that contain "/Load/Textures/GMS/" in their path,
    # stripping everything up to and including that marker.
    MARKER = "/Load/Textures/GMS/"
    dest_root = C.FULL_PACK_DIR
    dest_root.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            # Normalise Windows-style separators that some zippers produce.
            name_norm = name.replace("\\", "/")
            idx = name_norm.find(MARKER)
            if idx == -1:
                continue                         # junk at top level — skip
            # Remainder after the marker, e.g. "GMS/tex1_256x256_…"
            rel = name_norm[idx + len(MARKER):]
            if not rel or rel.endswith("/"):
                continue                         # directory entry
            # Guard against path traversal (e.g. "../../../etc/passwd").
            target = (dest_root / rel).resolve()
            if not str(target).startswith(str(dest_root.resolve())):
                log(f"  [skip path-traversal attempt: {rel}]")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            count += 1
    log(f"Full HD pack extracted: {count} files → {dest_root}.")


def apply(sel: str, *, log=_noop) -> dict:
    """Apply the chosen HD texture selection and return [Video_Settings] keys.

    sel is "off" | "portals" | "full".

      "portals" — installs the GMSE01 symlink (shadowing GMS) and enables
                  HiresTextures. Behavior is identical to the old apply(True).
      "full"    — ensures the full pack is extracted to GMS/, then removes our
                  GMSE01 symlink so Dolphin falls back to GMS. Raises
                  FileExistsError if GMSE01 is a real user directory (not our
                  symlink) — the caller must resolve that manually.
      "off"     — disables HiresTextures. Never removes files.
    """
    if sel == "portals":
        ensure_installed(log=log)
        log("HD textures: portals mode ON — HiresTextures enabled for SMS.")
        return video_settings(True)
    if sel == "full":
        ensure_full_installed(log=log)
        # Un-shadow: remove our GMSE01 symlink so Dolphin falls back to GMS.
        dest = C.HIRES_DEST
        if dest.is_symlink():
            dest.unlink()
            log(f"Removed portals symlink ({dest.name}) — Dolphin will fall "
                "back to Load/Textures/GMS (full pack).")
        elif dest.exists():
            # A real directory the user put there: we must not delete it.
            raise FileExistsError(
                f"{dest} is a real directory (not our symlink) — leaving it "
                "alone. Move/remove it yourself to let Dolphin fall back to GMS.")
        log("HD textures: full pack mode ON — HiresTextures enabled for SMS.")
        return video_settings(True)
    # "off" (or any unrecognised value treated as off)
    log("HD textures OFF — HiresTextures disabled for SMS (pack left on disk).")
    return video_settings(False)
