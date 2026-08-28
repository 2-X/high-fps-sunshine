#!/usr/bin/env python3
"""Install BSMSO character-skin packs onto the disc and rebuild the ISOs.

The game loads skins from /data/bsmso_models/<id>.arc on the DISC (see
skins.py). The Windows BSMSO launcher does this sync itself; our Mac kit
boots prebuilt ISOs, so this script does the equivalent once:

  1. Copy every pack from the upstream CustomModels/ folder into
     <root>/files/data/bsmso_models/, renamed display-name -> model id
     per library.json (Luigi.arc -> cadf67c6.arc).
  2. (--rebuild) Rebuild both ISOs with pyisotools from the same root:
     the highfps fork ISO from the root as-is (the root's kxe IS the fork
     build), and the stock-FPS ISO with the .orig-v400 kxe swapped in for
     the duration of its build.

Builds land next to the existing ISOs as *.new.iso first and are renamed
over the originals only on success, so a failed/interrupted build never
eats a working disc. Dolphin must not be running from these ISOs mid-swap.

Works on Windows too (paths default per-platform, same as smslaunch
config): pip install pyisotools, then run with --rebuild.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BSMSO_DIR = Path(__file__).resolve().parents[1]
WIN = sys.platform == "win32"

DEFAULT_PACKS = BSMSO_DIR / "upstream" / "BSMSO_1.1" / "CustomModels"
DEFAULT_WORK = (Path(r"C:\Users\krisb\kris-documents\games\dolphin\bsmso-work")
                if WIN else Path("/Applications/gamecube/bsmso-work"))
MODELS_SUBDIR = Path("files") / "data" / "bsmso_models"
ISO_STOCK = "BSMSO-GMSE01.iso"
ISO_HIGHFPS = "BSMSO-GMSE01-highfps.iso"
KXE_REL = Path("files") / "Kuribo!" / "Mods" / "BetterSunshineEngine.kxe"


def _builder_python() -> str:
    """Prefer the repo venv (has pyisotools); else this interpreter."""
    venv = BSMSO_DIR / "venv" / ("Scripts/python.exe" if WIN else "bin/python")
    if venv.exists():
        return str(venv)
    return sys.executable


def install_packs(packs: Path, root: Path) -> int:
    lib = packs / "library.json"
    if not lib.exists():
        sys.exit(f"error: {lib} not found — point --packs at the upstream "
                 f"BSMSO_1.1/CustomModels folder (it ships in the mod zip)")
    id_to_name = json.loads(lib.read_text())
    dest = root / MODELS_SUBDIR
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for model_id, name in sorted(id_to_name.items()):
        src = packs / f"{name}.arc"
        if not src.exists():
            print(f"  WARNING: {src.name} missing from pack folder — skipped")
            continue
        shutil.copyfile(src, dest / f"{model_id}.arc")
        print(f"  {src.name:<20} -> bsmso_models/{model_id}.arc")
        n += 1
    print(f"Installed {n} pack(s) into {dest}")
    return n


def build_iso(root: Path, dest: Path):
    """pyisotools build root -> dest, atomically via dest.new.iso."""
    tmp = dest.with_suffix(".new.iso")
    if tmp.exists():
        tmp.unlink()
    print(f"Building {dest.name} … (a few minutes; ~1.4GB)")
    subprocess.run(
        [_builder_python(), "-m", "pyisotools", str(root), "B",
         "--dest", str(tmp)],
        check=True,
    )
    if not tmp.exists() or tmp.stat().st_size < 1_000_000_000:
        sys.exit(f"error: build produced no/truncated ISO at {tmp}")
    tmp.replace(dest)
    print(f"  OK: {dest} ({dest.stat().st_size:,} bytes)")


def rebuild_isos(root: Path, iso_dir: Path, stock_kxe: Path):
    # 1. highfps fork ISO — root as-is (root kxe == the fork build; verified
    #    identical to sunshine/bsmso/BetterSunshineEngine-highfps-v400.kxe).
    build_iso(root, iso_dir / ISO_HIGHFPS)

    # 2. stock ISO — swap the v4.0.0 release kxe in just for this build.
    kxe = root / KXE_REL
    if not stock_kxe.exists():
        print(f"NOTE: {stock_kxe} not found — skipping the stock "
              f"{ISO_STOCK} rebuild (fork ISO already done)")
        return
    fork_bytes = kxe.read_bytes()
    try:
        shutil.copyfile(stock_kxe, kxe)
        build_iso(root, iso_dir / ISO_STOCK)
    finally:
        kxe.write_bytes(fork_bytes)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--packs", type=Path, default=DEFAULT_PACKS,
                   help="upstream CustomModels/ folder (with library.json)")
    p.add_argument("--work", type=Path, default=DEFAULT_WORK,
                   help="bsmso-work dir holding bsmso-root/ and the ISOs")
    p.add_argument("--rebuild", action="store_true",
                   help="rebuild both ISOs after installing the packs")
    args = p.parse_args()

    root = args.work / "bsmso-root" / "root"
    if not (root / "sys" / "main.dol").exists():
        sys.exit(f"error: {root} is not an extracted game root")

    install_packs(args.packs, root)
    if args.rebuild:
        rebuild_isos(root, args.work, args.work / "BetterSunshineEngine.kxe.orig-v400")
    else:
        print("Packs installed into the root only — rerun with --rebuild "
              "(or rebuild manually) to bake them into the ISOs.")


if __name__ == "__main__":
    main()
