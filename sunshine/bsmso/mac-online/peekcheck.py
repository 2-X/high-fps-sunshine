"""Live verify of the EFB peek 30Hz gate under BSE: hook words armed, guard
global correct, and gate-entry counter rates (tick once per rendered frame
reaching each callback, so the rate ~= rendered fps). Run while IN A STAGE.

Usage: python peekcheck.py [--seconds 3]
"""
import argparse
import struct
import sys
import time

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")
from gcmem import DolphinMem, find_dolphin_pid

MARIO_HOOK, SUN_HOOK = 0x8024D17C, 0x8002E270
MARIO_CTR, SUN_CTR = 0x80001700, 0x80001704
FR_GLOBAL = 0x804167B8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=3.0)
    args = ap.parse_args()

    m = DolphinMem(find_dolphin_pid())
    if not m.locate_comm_buffer():
        raise SystemExit("comm buffer not found — be in a stage (not title screen)")

    def r32(a):
        b = m.read(a, 4)
        return struct.unpack(">I", b)[0] if b else None

    for name, addr in (("mario", MARIO_HOOK), ("sun", SUN_HOOK)):
        w = r32(addr)
        state = ("C2-hooked" if w is not None and (w >> 26) == 18
                 else "STOCK mflr (gate NOT applied)" if w == 0x7C0802A6
                 else "UNEXPECTED")
        print(f"{name} hook @{addr:08X}: {w:08X}  {state}")
    fr = r32(FR_GLOBAL)
    print(f"framerate global: {fr:08X}  "
          f"({'guard passes (4.0f)' if fr == 0x40800000 else 'guard passes (2.0f)' if fr == 0x40000000 else 'guard FAILS -> gates inert'})")

    a1, b1 = r32(MARIO_CTR), r32(SUN_CTR)
    time.sleep(args.seconds)
    a2, b2 = r32(MARIO_CTR), r32(SUN_CTR)
    dt = args.seconds
    print(f"gate entry rate: mario {(a2 - a1) / dt:.0f}/s  sun {(b2 - b1) / dt:.0f}/s"
          f"  (~rendered fps; 0 = hook dead)")


if __name__ == "__main__":
    main()
