"""One-shot "warp to player" — the Windows launcher's warp intent, from the CLI.

Why: puppets only render for peers on the SAME stage AND episode
(PROTOCOL.md §C.2). Two players with different story progress land in
different Delfino episodes and never see each other even though both are
on the server. The mod's own fix is the warp intent: the bridge writes a
target into the control block and raises BridgeFlags.WarpPending; the game
module performs the warp on its next comm poll (ApplyWarpIntentToControlSpan
in the reference launcher).

Reads the target's live position straight from RemoteSnapshots[slot] in the
local comm buffer — the bridge keeps it fresh — so there is no network I/O
here at all. Run while in a stage with the bridge attached:

    python3 warp_to_player.py --name Kris-PC
    python3 warp_to_player.py --slot 0
"""
import argparse
import struct
import sys
import time

from macmem import DolphinMem, find_dolphin_pid
from protocol import (
    COMM_BRIDGE_CONTROL_OFFSET,
    COMM_REMOTE_SNAPSHOTS_OFFSET,
    PlayerSnapshot,
    SNAPSHOT_SIZE,
)

BRIDGE_FLAG_WARP_PENDING = 0x4
WARP_FIELDS_OFFSET = 13          # WarpTargetSlot u8, then course/episode/pos/facing
MAX_SLOTS = 10


def _read_remote(mem: DolphinMem, slot: int) -> PlayerSnapshot | None:
    raw = mem.read_comm()
    if raw is None:
        return None
    off = COMM_REMOTE_SNAPSHOTS_OFFSET + SNAPSHOT_SIZE * slot
    snap = PlayerSnapshot.unpack_comm(raw[off:off + SNAPSHOT_SIZE])
    return snap if snap.connected else None


def main():
    ap = argparse.ArgumentParser()
    tgt = ap.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--slot", type=int, help="target slot (0-9)")
    tgt.add_argument("--name", help="target player name (as on the server)")
    args = ap.parse_args()

    pid = find_dolphin_pid()
    if pid is None:
        sys.exit("Dolphin is not running.")
    mem = DolphinMem(pid)
    if mem.locate_comm_buffer() is None:
        sys.exit("Comm buffer not found — be in a stage with the game booted.")

    slot = args.slot
    if slot is None:
        want = args.name.encode("utf-8")
        for s in range(MAX_SLOTS):
            snap = _read_remote(mem, s)
            if snap and snap.name.rstrip(b"\x00") == want:
                slot = s
                break
        if slot is None:
            sys.exit(f"No connected remote named {args.name!r} in the comm buffer "
                     "(bridge running? peer online?)")

    snap = _read_remote(mem, slot)
    if snap is None:
        sys.exit(f"Slot {slot} has no live snapshot.")
    name = snap.name.rstrip(b"\x00").decode("utf-8", "replace")
    print(f"Target: slot {slot} ({name}) stage {snap.stage_id} ep {snap.episode_id} "
          f"pos ({snap.pos_x:.0f}, {snap.pos_y:.0f}, {snap.pos_z:.0f})")

    # Warp fields @13..31: slot, course, episode, pos xyz, facing (all BE).
    fields = struct.pack(
        ">BBBffff",
        slot & 0xFF,
        snap.stage_id & 0xFF,
        snap.episode_id & 0xFF,
        snap.pos_x, snap.pos_y, snap.pos_z,
        snap.rotation_y,
    )
    if not mem.write_comm_subregion(WARP_FIELDS_OFFSET, fields):
        sys.exit("Failed to write warp fields.")

    # Raise BridgeFlags.WarpPending (u32 BE @6), read-modify-write.
    raw = mem.read_comm()
    flags = struct.unpack_from(">I", raw, COMM_BRIDGE_CONTROL_OFFSET)[0]
    if not mem.write_comm_subregion(
            COMM_BRIDGE_CONTROL_OFFSET,
            struct.pack(">I", flags | BRIDGE_FLAG_WARP_PENDING)):
        sys.exit("Failed to raise WarpPending.")
    print(f"WarpPending raised (flags {flags:#x} -> "
          f"{flags | BRIDGE_FLAG_WARP_PENDING:#x}). Watching for the game to "
          "consume it…")

    for _ in range(20):
        time.sleep(0.5)
        raw = mem.read_comm()
        if raw is None:
            print("Comm buffer vanished — stage transition in progress (good sign).")
            return
        cur = struct.unpack_from(">I", raw, COMM_BRIDGE_CONTROL_OFFSET)[0]
        if not (cur & BRIDGE_FLAG_WARP_PENDING):
            print("Game consumed the warp intent. You should be loading now.")
            return
    print("WarpPending still set after 10s — the game did not consume it "
          "(wrong stage state, or the module ignores slot-warp; try again in "
          "an active stage).")


if __name__ == "__main__":
    main()
