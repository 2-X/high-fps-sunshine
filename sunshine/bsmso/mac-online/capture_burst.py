#!/usr/bin/env python3
"""capture_burst.py — live FLUDD / hover-burst state capture for BSMSO.

Purpose
-------
Answer the one question that decides whether the "friend's hover-burst shows as a
plain spray on my screen" bug is a *puppet-only* fix or needs a protocol change:

    Does a hover-burst produce a DISTINCT, already-transmitted signal
    (AnimId / ActionId nerve / VfxFlags) versus a normal hover or spray?

Everything this tool watches is exactly what _BSMSO.kxe ships to other players in the
64-byte LocalSnapshot (PROTOCOL.md A.3). If the burst is distinguishable HERE, then a
friend's stock client already sends enough for our client to render it — i.e. Tier-1,
patch only our _BSMSO.kxe puppet path, no wire/interop change.

What it reads
-------------
* LocalSnapshot @ comm+48 (the outbound slot _BSMSO writes every frame — no server or
  bridge required, just the game in a stage). Decoded via protocol.PlayerSnapshot.
* Live TMario nozzle byte, read directly from the game as an independent cross-check:
  gpMarioAddress(0x8040E108) -> TMario -> mFludd(+0x3E4) -> currentNozzle(+0x1C84).

How to use
----------
1. Boot the BSMSO ISO in our Dolphin, get into a stage (Delfino Plaza is fine) with
   FLUDD equipped. No server/bridge needed.
2. Run:  python3 capture_burst.py
3. Follow the on-screen script: it prints a line every time a watched field changes.
   Press ENTER at any moment to drop a "===== MARK =====" line into the log so you can
   correlate "I pressed burst NOW" with the field changes around it.
4. Do each action deliberately, pressing ENTER right before each:
       a. stand still (baseline)
       b. normal spray (square-nozzle spray)
       c. equip Hover, normal hover
       d. Hover Burst   <-- the move we care about
       e. any other moveset move you want mapped (SMO Dive, Rocket Dive, ...)
5. Ctrl-C to stop. Full detail is also written to /tmp/burst-capture.log.

Reading the output: compare the AnimId / Action(full) / VfxFlags between (c) and (d).
If (d) has an AnimId or Action value (c) never shows, the burst is distinguishable and
Tier-1 is on. If they're identical, we fall to Tier-2 (add a VfxFlags bit).
"""

import argparse
import struct
import sys
import threading
import time
from datetime import datetime

from macmem import DolphinMem, find_dolphin_pid
from protocol import PlayerSnapshot, COMM_LOCAL_SNAPSHOT_OFFSET, SNAPSHOT_SIZE

# --- NTSC-U symbols (us.map) --------------------------------------------------
GP_MARIO_ADDRESS = 0x8040E108   # global holding the live TMario* (guest addr)
TMARIO_FLUDD_OFF = 0x3E4        # TMario -> TWaterGun* mFludd
TWATERGUN_NOZZLE = 0x1C84       # TWaterGun -> u8 current nozzle index
TMARIO_BUTTONS   = 0x7C         # TMario -> u32 held-button word (GC PAD bits).
                                # Confirmed: BetterSunshineMoveset reads mario+0x7c and
                                # masks 0x800(Y)/0x40(L)/0x20(R) to detect its moves.

MEM1_LO, MEM1_HI = 0x80000000, 0x81800000

# GameCube PAD button bits (PADStatus.button)
BUTTON_BITS = [
    (0x8000, "ERR"), (0x0080, "?80"),
    (0x1000, "Start"), (0x0800, "Y"), (0x0400, "X"), (0x0200, "B"), (0x0100, "A"),
    (0x0040, "L"), (0x0020, "R"), (0x0010, "Z"),
    (0x0008, "Up"), (0x0004, "Down"), (0x0002, "Right"), (0x0001, "Left"),
]


def decode_buttons(b: int) -> str:
    names = [n for bit, n in BUTTON_BITS if b & bit]
    return "+".join(names) if names else "-"

# VfxFlags bit names (PROTOCOL.md A.3 / _BSMSO VfxFlags enum @ SMSO.Net L9493)
VFX_BITS = [
    (0x001, "WaterSpray"),
    (0x002, "Hover"),
    (0x004, "Rocket"),
    (0x008, "Turbo"),
    (0x010, "Dead"),
    (0x020, "FluddEmpty"),
    (0x040, "YCam"),
    (0x080, "NozzleSwitching"),
    (0x100, "WetSlide"),
    (0x200, "NoFludd"),
    (0x400, "YoshiFruitMouth"),
]

# Tentative nozzle-index legend (from _BSMSO disasm: valid-emit mask 0x32 => {1,4,5};
# hover==4, turbo==5, spray==1 observed). Marked '?' — the capture is the ground truth.
NOZZLE_NAMES = {0: "0", 1: "Spray?", 2: "2", 3: "Rocket?", 4: "Hover?", 5: "Turbo?"}

# Fields whose CHANGE triggers a log line. anim_frame is deliberately excluded (it
# ticks every frame); it's shown in the detail but never triggers on its own.
TRIGGER_FIELDS = [
    "anim_id", "nozzle_id", "water", "vfx_flags",
    "movement_state", "action_id", "action_id_hi",
]


def decode_vfx(flags: int) -> str:
    names = [name for bit, name in VFX_BITS if flags & bit]
    extra = flags & ~sum(bit for bit, _ in VFX_BITS)
    if extra:
        names.append(f"UNK:{extra:#06x}")
    return "|".join(names) if names else "-"


def full_action(snap: PlayerSnapshot) -> int:
    return ((snap.action_id_hi & 0xFFFF) << 16) | (snap.action_id & 0xFFFF)


def _live_mario(mem: DolphinMem):
    raw = mem.read(GP_MARIO_ADDRESS, 4)
    if not raw:
        return None
    mario = struct.unpack(">I", raw)[0]
    return mario if (MEM1_LO <= mario < MEM1_HI) else None


def read_live_nozzle(mem: DolphinMem):
    """Best-effort direct read of TMario's current FLUDD nozzle. Returns int or None."""
    try:
        mario = _live_mario(mem)
        if mario is None:
            return None
        raw = mem.read(mario + TMARIO_FLUDD_OFF, 4)
        if not raw:
            return None
        fludd = struct.unpack(">I", raw)[0]
        if not (MEM1_LO <= fludd < MEM1_HI):
            return None
        raw = mem.read(fludd + TWATERGUN_NOZZLE, 1)
        return raw[0] if raw else None
    except Exception:
        return None


def read_buttons(mem: DolphinMem):
    """Best-effort direct read of TMario's held-button word. Returns int or None."""
    try:
        mario = _live_mario(mem)
        if mario is None:
            return None
        raw = mem.read(mario + TMARIO_BUTTONS, 4)
        return struct.unpack(">I", raw)[0] & 0xFFFF if raw else None
    except Exception:
        return None


def snap_fields(snap: PlayerSnapshot) -> dict:
    return {f: getattr(snap, f) for f in TRIGGER_FIELDS}


def fmt_line(snap: PlayerSnapshot, live_nozzle, changed: set,
             buttons=None, pressed=0, btn_changed=False) -> str:
    def mark(field, text):
        return f"[{text}]" if field in changed else f" {text} "
    noz = NOZZLE_NAMES.get(snap.nozzle_id, str(snap.nozzle_id))
    live = "" if live_nozzle is None else f" liveNoz={live_nozzle}({NOZZLE_NAMES.get(live_nozzle, '?')})"
    btn = ""
    if buttons is not None:
        held = decode_buttons(buttons)
        press = decode_buttons(pressed)
        held_txt = f"[{held}]" if btn_changed else f" {held} "
        btn = f" btn={held_txt}" + (f" +PRESS:{press}" if pressed else "")
    return (
        f"anim={mark('anim_id', f'{snap.anim_id:5d}')}"
        f"act={mark('action_id', f'{full_action(snap):#010x}')}"
        f"noz={mark('nozzle_id', f'{snap.nozzle_id}:{noz:<7}')}"
        f"water={mark('water', f'{snap.water:3d}')}"
        f"mov={mark('movement_state', f'{snap.movement_state:3d}')}"
        f"vfx={mark('vfx_flags', f'{snap.vfx_flags:#06x}')} {decode_vfx(snap.vfx_flags)}"
        f"{btn}{live} (frame={snap.anim_frame})"
    )


def diff_str(prev: dict, cur: dict) -> str:
    parts = []
    for f in TRIGGER_FIELDS:
        if prev.get(f) != cur.get(f):
            parts.append(f"{f}:{prev.get(f)}->{cur.get(f)}")
    return ", ".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hz", type=float, default=120.0, help="poll rate (default 120)")
    ap.add_argument("--log", default="/tmp/burst-capture.log", help="detail log path")
    ap.add_argument("--all", action="store_true",
                    help="print EVERY poll, not just changes (very noisy)")
    args = ap.parse_args()

    pid = find_dolphin_pid()
    if pid is None:
        print("No Dolphin process found. Boot the BSMSO ISO first.", file=sys.stderr)
        sys.exit(1)
    print(f"Found Dolphin pid={pid}")

    try:
        mem = DolphinMem(pid)
    except PermissionError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print("Locating comm buffer (get into a stage with FLUDD if this hangs)…")
    guest_comm = None
    for _ in range(60):  # ~30s of retries
        guest_comm = mem.locate_comm_buffer()
        if guest_comm is not None:
            break
        time.sleep(0.5)
    if guest_comm is None:
        print("Comm buffer NOT FOUND. Is _BSMSO.kxe loaded and are you in a stage?",
              file=sys.stderr)
        sys.exit(1)
    snap_addr = guest_comm + COMM_LOCAL_SNAPSHOT_OFFSET
    print(f"Comm buffer @ {guest_comm:#010x}  (LocalSnapshot @ {snap_addr:#010x})")

    logf = open(args.log, "w")

    def logboth(s: str):
        print(s)
        logf.write(s + "\n")
        logf.flush()

    logboth("")
    logboth("=" * 78)
    logboth("BURST CAPTURE — watching _BSMSO LocalSnapshot (what your friend transmits)")
    logboth("Script: press ENTER before each action, then perform it:")
    logboth("  (a) stand still  (b) normal spray  (c) normal hover  (d) HOVER BURST")
    logboth("Compare AnimId / act(full action) / vfx between (c) hover and (d) burst.")
    logboth("Ctrl-C to stop.  Full log: " + args.log)
    logboth("=" * 78)

    # Background thread: ENTER drops a MARK line.
    mark_counter = [0]

    def mark_reader():
        for _ in sys.stdin:
            mark_counter[0] += 1
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            logboth(f"\n===== MARK #{mark_counter[0]}  {ts} =====")

    threading.Thread(target=mark_reader, daemon=True).start()

    prev = None
    prev_btn = None
    period = 1.0 / args.hz
    misses = 0
    try:
        while True:
            data = mem.read(snap_addr, SNAPSHOT_SIZE)
            if not data or len(data) < SNAPSHOT_SIZE:
                misses += 1
                if misses in (30, 300):
                    logboth("(warning: LocalSnapshot read failing — game paused / not in stage?)")
                time.sleep(period)
                continue
            misses = 0
            snap = PlayerSnapshot.unpack_comm(data)
            cur = snap_fields(snap)
            buttons = read_buttons(mem)
            btn_changed = buttons is not None and buttons != prev_btn
            pressed = (buttons & ~(prev_btn or 0)) if buttons is not None else 0  # rising edge
            if args.all or prev is None or cur != prev or btn_changed:
                changed = {f for f in TRIGGER_FIELDS if prev is None or cur[f] != prev[f]}
                live_nozzle = read_live_nozzle(mem) if changed or prev is None else None
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                logboth(f"{ts}  {fmt_line(snap, live_nozzle, changed, buttons, pressed, btn_changed)}")
                if prev is not None and changed:
                    logf.write(f"          changed: {diff_str(prev, cur)}\n")
                    logf.flush()
                prev = cur
            prev_btn = buttons
            time.sleep(period)
    except KeyboardInterrupt:
        logboth("\nStopped.")
    finally:
        logf.close()
        mem.close()


if __name__ == "__main__":
    main()
