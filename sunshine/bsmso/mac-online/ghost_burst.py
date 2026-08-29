"""BSMSO burst-replay ghost — a puppet that stands next to the live player and
cycles between plain HOVER and HOVER BURST, so we can watch how _BSMSO renders
each on the observer's screen (and diff the puppet state).

Reuses the follow logic from ghost_bot.py. The puppet parks a fixed offset from
the live player and, in --mode toggle (default), alternates every --period seconds:

  * HOVER (plain):  nozzle=hover(0x44), vfx=Hover(0x02),      act=0x0c400201 anim=195
  * BURST:          nozzle=hover(0x44), vfx=Hover|WaterSpray(0x03), act=0x0000088b anim=86

Field values are exactly what capture_burst.py recorded for a real hover-burst
(/tmp/burst-capture2.log): burst nerve 0x088b / anim 86 / WaterSpray+Hover.

    python3 ghost_burst.py --server 127.0.0.1 --name Burst [--mode toggle|burst|hover]
                           [--period 2.5] [--offx 150 --offz 0]

Needs: server (run_server.sh) + your live bridge (bridge.py) running, and you
in a stage. The puppet only renders on the stage the live player is on.
"""
import argparse
import sys
import time
import threading

from netclient import NetClient, JoinError
from protocol import PlayerSnapshot, DEFAULT_PORT

# States captured from a real hover-burst (see module docstring).
NOZZLE_HOVER = 0x44          # 0x40 | 4  (consumer masks &0xF -> 4 = hover)
VFX_HOVER      = 0x02        # Hover
VFX_HOVER_SPRAY = 0x03       # Hover | WaterSpray  (the emit/burst)

STATE_HOVER = dict(anim_id=195, action_id=0x0201, action_id_hi=0x0c40,
                   vfx_flags=VFX_HOVER,       movement_state=125)
STATE_BURST = dict(anim_id=86,  action_id=0x088b, action_id_hi=0x0000,
                   vfx_flags=VFX_HOVER_SPRAY, movement_state=120)


def run(host, name, port, mode, period, offx, offy, offz, water, hz):
    latest = {"seen": False, "stage": 1, "episode": 0, "x": 0.0, "y": 500.0, "z": 0.0}
    lock = threading.Lock()

    def on_batch(entries):
        with lock:
            for slot, seq, snap in entries:
                if slot != client.assigned_slot and snap.connected:
                    latest.update(seen=True, stage=snap.stage_id, episode=snap.episode_id,
                                  x=snap.pos_x, y=snap.pos_y, z=snap.pos_z)

    client = NetClient(host, port=port, on_snapshot_batch=on_batch)
    try:
        slot = client.join(name)
        print(f"[burst] joined slot {slot} (name={name}) mode={mode}")
    except JoinError as e:
        print(f"[burst] join failed: {e}", file=sys.stderr)
        client.close(); return

    interval = 1.0 / hz
    t_start = time.monotonic()
    last_label = None
    try:
        while True:
            t0 = time.monotonic()
            with lock:
                seen = latest["seen"]
                stage, episode = latest["stage"], latest["episode"]
                cx, cy, cz = latest["x"], latest["y"], latest["z"]
            if not seen:
                stage, episode, cx, cy, cz = 1, 0, 0.0, 500.0, 0.0

            if mode == "burst":
                st, label = STATE_BURST, "BURST"
            elif mode == "hover":
                st, label = STATE_HOVER, "HOVER"
            else:  # toggle
                phase = int((t0 - t_start) / period) % 2
                st, label = (STATE_BURST, "BURST") if phase else (STATE_HOVER, "HOVER")
            if label != last_label:
                print(f"[burst] -> {label}  (act={st['action_id']|(st['action_id_hi']<<16):#x} "
                      f"anim={st['anim_id']} vfx={st['vfx_flags']:#04x})")
                last_label = label

            snap = PlayerSnapshot(
                pos_x=cx + offx, pos_y=cy + offy, pos_z=cz + offz,
                vel_x=0.0, vel_y=0.0, vel_z=0.0,
                rotation_y=180.0,
                nozzle_id=NOZZLE_HOVER, water=water,
                health=8, stage_id=stage, episode_id=episode,
                connected=1, slot=slot, ping_ms=0,
                name=name.encode("utf-8")[:16].ljust(16, b"\x00"),
                anim_frame=int(time.monotonic() * 30) & 0xFFFF,
                **st,
            )
            client.send_snapshot(snap)

            sleep_for = interval - (time.monotonic() - t0)
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        print(f"\n[burst] shutting down slot {slot}")
    finally:
        client.close()


def main():
    p = argparse.ArgumentParser(description="BSMSO burst-replay ghost")
    p.add_argument("--server", required=True)
    p.add_argument("--name", default="Burst")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--mode", choices=["toggle", "burst", "hover"], default="toggle")
    p.add_argument("--period", type=float, default=2.5, help="toggle period (s)")
    p.add_argument("--offx", type=float, default=150.0)
    p.add_argument("--offy", type=float, default=0.0)
    p.add_argument("--offz", type=float, default=0.0)
    p.add_argument("--water", type=int, default=200)
    p.add_argument("--hz", type=float, default=60.0)
    a = p.parse_args()
    run(a.server, a.name, a.port, a.mode, a.period, a.offx, a.offy, a.offz, a.water, a.hz)


if __name__ == "__main__":
    main()
