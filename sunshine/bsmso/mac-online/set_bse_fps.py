#!/usr/bin/env python3
"""Set BSE's Frame Rate directly in Dolphin RAM — no comm buffer / stage needed.

Works from the title screen on: finds MEM1 by the GMSE01 disc header at a
region base (the comm-buffer anchor only exists in an active stage, but the
disc header and the BSE Setting objects exist from boot), then locates the
Frame Rate setting via bridge.locate_bse_settings() (old-kxe fast path, or
name-string scan on the fork kxe), writes the enum, and confirms BSE picked it
up by watching the framerate global 0x804167B8 flip to FPS/60.

Usage: python3 set_bse_fps.py [--fps 120]
"""
import argparse
import struct
import sys
import time

from gcmem import DolphinMem, find_dolphin_pid, MEM1_GUEST_BASE
from bridge import locate_bse_settings, BSE_FPS_ENUM

FRAMERATE_GLOBAL = 0x804167B8
MEM1_MIN_SIZE = 0x01800000


def find_mem1_base(mem: DolphinMem, timeout_s: float = 30.0) -> bool:
    """Locate MEM1 by the Sunshine-family disc header (GMSE**) at a region base;
    set the host base. Matches GMSE01 (retail/BSMSO) and GMSE11 (Sunset)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for rb, rs in mem._regions():
            if rs >= MEM1_MIN_SIZE and mem._raw_read(rb, 4) == b"GMSE":
                mem._mem1_host_base = rb
                return True
        time.sleep(1.0)
    return False


def read_framerate_global(mem: DolphinMem):
    b = mem.read(FRAMERATE_GLOBAL, 4)
    return struct.unpack(">f", b)[0] if b and len(b) == 4 else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fps", type=int, default=120,
                   choices=sorted(BSE_FPS_ENUM), help="target frame rate")
    p.add_argument("--aspect", type=int, default=3,
                   help="BSE aspect enum (3=16:9 WIDE, 2=16:10, 4=21:9; "
                        "-1 to skip)")
    args = p.parse_args()
    enum = BSE_FPS_ENUM[args.fps]
    target_global = args.fps / 60.0

    pid = find_dolphin_pid()
    if pid is None:
        sys.exit("no Dolphin process found")
    mem = DolphinMem(pid)
    print(f"[fps] Dolphin pid={pid}")

    if not find_mem1_base(mem):
        sys.exit("MEM1 not found — is a game booted (GMSE** header not present)?")
    print(f"[fps] MEM1 located (host base 0x{mem._mem1_host_base:x})")

    # The BSE module registers its Setting objects a few seconds into boot —
    # retry until they appear (or time out).
    deadline = time.monotonic() + 60.0
    fps_addr = None
    while time.monotonic() < deadline:
        found = locate_bse_settings(mem)
        fps_addr = found.get("fps")
        if fps_addr is not None:
            break
        time.sleep(1.0)
    if fps_addr is None:
        sys.exit("BSE 'Frame Rate' setting not found in MEM1 — is this a BSE/BSMSO ISO?")

    # Aspect must land BEFORE scene setup or the scene keeps a 4:3 projection
    # that just gets display-stretched; set it here alongside FPS.
    aspect_addr = found.get("aspect")
    if aspect_addr is not None and 0 <= args.aspect <= 5:
        cur_a = struct.unpack(">i", mem.read(aspect_addr, 4))[0]
        if cur_a != args.aspect:
            mem.write(aspect_addr, struct.pack(">i", args.aspect))
            print(f"[fps] wrote aspect = {args.aspect} (was {cur_a}) @0x{aspect_addr:08X}")
        else:
            print(f"[fps] aspect already {cur_a}")

    cur = struct.unpack(">i", mem.read(fps_addr, 4))[0]
    before = read_framerate_global(mem)
    print(f"[fps] mFPSValue @0x{fps_addr:08X} = {cur}; framerate global = {before}")

    if cur != enum:
        if not mem.write(fps_addr, struct.pack(">i", enum)):
            sys.exit("write failed")
        print(f"[fps] wrote mFPSValue = {enum} ({args.fps}fps)")
    else:
        print(f"[fps] mFPSValue already {enum}")

    # BSE's updateFPS() rewrites 0x804167B8 every frame; watch it flip.
    for _ in range(20):
        g = read_framerate_global(mem)
        if g is not None and abs(g - target_global) < 1e-3:
            print(f"[fps] CONFIRMED: framerate global = {g} — BSE is at {args.fps}fps")
            return
        time.sleep(0.1)
    print(f"[fps] WARNING: framerate global still {read_framerate_global(mem)} "
          f"(expected {target_global}) — BSE may not have applied the value yet")


if __name__ == "__main__":
    main()
