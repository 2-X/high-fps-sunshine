"""Analyze a PresentMon CSV: is the panel getting K*rate evenly-spaced images,
or rate bunched pairs (blend+real back-to-back)?

The interp pacer question (HANDOFF-360-INTERP.md): at 180x2, a WORKING pacer
shows present gaps ~2.8/2.8ms; a degenerate one (v2.5) shows ~0/5.6 alternating.
msBetweenDisplayChange is the ground truth for what the panel actually showed.

Usage: python present_cadence.py capture.csv [--target-fps 180] [--interp 2]
Works with PresentMon 1.x columns (msBetweenPresents) and 2.x (FrameTime etc).
Capture with pm_capture.ps1 (elevates itself; passive, never touches the game).
"""
import argparse
import csv
import statistics
import sys


def pick(row, *names):
    for n in names:
        for k in row:
            if k.strip().lower() == n.lower():
                return row[k]
    return None


def load(path):
    presents, displays, dropped = [], [], 0
    with open(path, newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            bp = pick(row, "msBetweenPresents", "MsBetweenPresents", "FrameTime")
            bd = pick(row, "msBetweenDisplayChange", "MsBetweenDisplayChange",
                      "DisplayedTime")
            dr = pick(row, "Dropped")
            try:
                if bp is not None and bp != "" and float(bp) > 0:
                    presents.append(float(bp))
            except ValueError:
                pass
            try:
                if dr is not None and int(float(dr)) == 1:
                    dropped += 1
                elif bd is not None and bd != "" and float(bd) > 0:
                    displays.append(float(bd))
            except ValueError:
                pass
    return presents, displays, dropped


def stats(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    q = lambda p: xs[min(n - 1, int(p * n))]
    return dict(n=n, mean=statistics.fmean(xs), p1=q(0.01), p50=q(0.50),
                p99=q(0.99), lo=xs[0], hi=xs[-1])


def hist(xs, width=0.5, cap=12.0):
    from collections import Counter
    c = Counter(min(cap, round(x / width) * width) for x in xs)
    total = len(xs)
    lines = []
    for b in sorted(c):
        share = c[b] / total
        if share >= 0.01:
            bar = "#" * max(1, int(share * 50))
            lines.append(f"  {b:5.1f}ms  {share*100:5.1f}%  {bar}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--target-fps", type=int, default=180,
                    help="logic rate (distinct frames/s)")
    ap.add_argument("--interp", type=int, default=2, help="K (presents per frame)")
    args = ap.parse_args()

    presents, displays, dropped = load(args.csv_path)
    if not presents:
        sys.exit("no present rows parsed -- wrong CSV or empty capture?")

    slot = 1000.0 / (args.target_fps * args.interp)   # ideal sub-slot, ms
    frame = 1000.0 / args.target_fps                  # distinct-frame period, ms

    ps = stats(presents)
    print(f"== presents: n={ps['n']}  mean={ps['mean']:.2f}ms  "
          f"p1/p50/p99={ps['p1']:.2f}/{ps['p50']:.2f}/{ps['p99']:.2f}ms")
    print(hist(presents))

    # Bunching metric: fraction of gaps near 0 vs near the full frame period.
    tiny = sum(1 for x in presents if x < slot * 0.35) / len(presents)
    full = sum(1 for x in presents if x > frame * 0.75) / len(presents)
    even = sum(1 for x in presents if slot * 0.6 < x < slot * 1.4) / len(presents)
    print(f"   gaps <{slot*0.35:.1f}ms: {tiny*100:.0f}%   "
          f"~{slot:.1f}ms (even): {even*100:.0f}%   "
          f">{frame*0.75:.1f}ms (bunch stride): {full*100:.0f}%")

    if displays:
        ds = stats(displays)
        print(f"== displayed: n={ds['n']}  (+{dropped} dropped)  "
              f"mean={ds['mean']:.2f}ms  "
              f"p1/p50/p99={ds['p1']:.2f}/{ds['p50']:.2f}/{ds['p99']:.2f}ms")
        print(hist(displays))
    elif dropped:
        print(f"== displayed: no timing rows; {dropped} presents dropped")

    print()
    if tiny > 0.3 and full > 0.3:
        print(f"VERDICT: BUNCHED -- blend+real presented back-to-back; the panel "
              f"is effectively seeing {args.target_fps} unique images. "
              f"(v2.5 signature)")
    elif even > 0.7:
        print(f"VERDICT: EVEN -- ~{slot:.1f}ms cadence; true "
              f"{args.target_fps * args.interp} presents/s pacing. (working v3)")
    else:
        print("VERDICT: MIXED -- neither clean signature; eyeball the histogram "
              "(scene changes mid-capture? partial pacing?)")


if __name__ == "__main__":
    main()
