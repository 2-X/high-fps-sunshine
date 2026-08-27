"""Passive live bench: sample thread CPU + times-file tail over a window
while someone plays. Never touches input; never kills Dolphin.

Usage: python live_bench.py [--seconds 60] [--tag live]
"""
import argparse
import importlib.util
import os
import subprocess
import time

spec = importlib.util.spec_from_file_location(
    "benchmark",
    r"C:\code\high-fps-sunshine\sunshine\research\scripts\benchmark.py")
bm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bm)


def dolphin_pid():
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Dolphin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True).stdout.strip()
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2:
            return int(parts[1])
    raise SystemExit("Dolphin not running")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--tag", default="live")
    args = ap.parse_args()

    pid = dolphin_pid()
    udir = bm.user_dir()
    logs = os.path.join(udir, "Logs")
    render_f = os.path.join(logs, "render_times.txt")
    vblank_f = os.path.join(logs, "vblank_times.txt")

    eff, per_game, global_ = bm.effective_speed(udir)
    print(f"[{args.tag}] EmulationSpeed effective={eff} "
          f"(per-game {per_game} / global {global_}), pid={pid}")

    t0 = bm.thread_times(pid)
    w0 = time.time()
    time.sleep(args.seconds)
    t1 = bm.thread_times(pid)
    window = time.time() - w0

    # The emu appends to the times files as it runs; the tail of the file IS
    # the window just played (tail_slice walks back by cumulative ms).
    r = bm.stats(bm.parse_times(render_f), args.seconds)
    v = bm.stats(bm.parse_times(vblank_f), args.seconds)

    print(f"[{args.tag}] last {args.seconds}s of play:")
    print(f"  FPS (render): {r['hz']:.1f} mean | p1 {r['p1']:.2f} / "
          f"p50 {r['p50']:.2f} / p99 {r['p99']:.2f} ms | n={r['n']}")
    print(f"  VPS (vblank): {v['hz']:.1f} mean | p1 {v['p1']:.2f} / "
          f"p50 {v['p50']:.2f} / p99 {v['p99']:.2f} ms | n={v['n']}")
    print(f"  threads (% of one core over {window:.0f}s):")
    for pct, name in bm.thread_table(t0, t1, window):
        print(f"    {name}: {pct:.1f}%")


if __name__ == "__main__":
    main()
