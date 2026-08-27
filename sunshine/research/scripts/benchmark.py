#!/usr/bin/env python3
"""benchmark.py — reproducible fps-ceiling benchmark for the fork Dolphin.

Why this exists: every ceiling number in HANDOFF-PC.md was produced by hand
(launch, stare at a clock, taskkill, parse in a REPL) and half of session 1's
numbers were garbage because of cold shader caches and background load. This
codifies the method from HANDOFF-PC.md §7 so a run is one command:

  launch `Dolphin.exe -e <rom> -s <savestate> -b`  (boots into the state, no
  UI, character stands still — reproducible), wait --seconds, close Dolphin
  GRACEFULLY (the times files are written by the emu and finalized on clean
  shutdown), then parse the per-frame interval logs and report the TAIL only
  (shader cache needs ~80 s to warm; anything shorter measures the cache).

To measure the ceiling: set EmulationSpeed ABOVE what the host can deliver
(in User/GameSettings/GMSE01.ini [Core] — per HANDOFF-PC.md §1 that file
overrides both Dolphin.ini and the -C flag, so this script does NOT try to
set speed; it reports the effective value it found instead) and read the
delivered VPS. One unthrottled run answers "is target X reachable" for all X.

Where the times files live (verified by source grep, 2026-08-20):
  dolphin-src/Source/Core/VideoCommon/PerformanceMetrics.h:60-61 names them
  ("render_times.txt" / "vblank_times.txt") and PerformanceTracker.cpp:194
  opens File::GetUserPath(D_LOGS_IDX) + name with std::ios_base::out —
  i.e. <UserDir>/Logs/, TRUNCATED at the start of each run. The fork binary
  (dolphin-src/Binary/x64/Dolphin.exe) has no portable.txt, so UserDir is
  %APPDATA%/Dolphin Emulator — confirmed on this machine. Writes happen only
  if GFX.ini [Settings] LogRenderTimeToFile = True (PerformanceTracker.cpp:189);
  the script refuses to run if that flag is off. File format: one per-frame
  interval in ms per line; fps = 1000 * N / sum (HANDOFF-PC.md §7).

*** TRAP (HANDOFF-PC.md §S3.5): the savestate must be FRESHLY MADE under the
*** current code config. An old state restores stale in-game Gecko state
*** (GMSE01.s02 restored G=6.0 over whatever code was enabled). Dolphin-side
*** VPS/throughput numbers survive that, but any SPEED conclusion is invalid.
*** Savestates are also build-locked. Boot the current build, load your codes,
*** save a fresh state, then benchmark against that.

Thread utilization: per-thread kernel+user time deltas over the tail window,
named via GetThreadDescription (ctypes recipe lifted from pcprofile.py).

Usage:
  python benchmark.py --savestate 3 --seconds 150 --tag ceiling-240
  python benchmark.py --selftest        # parser math check, launches nothing
"""

import argparse
import ctypes
import datetime
import os
import subprocess
import sys
import time
from ctypes import wintypes

# --- fixed locations ---------------------------------------------------------
DOLPHIN_EXE = r"C:\code\high-fps-sunshine\dolphin-src\Binary\x64\Dolphin.exe"
DEFAULT_ROM = (r"C:\Users\krisb\kris-documents\games\dolphin"
               r"\Super Mario Sunshine (USA).rvz")
BENCH_LOG = r"C:\code\high-fps-sunshine\sunshine\research\bench-log.md"
GAME_ID = "GMSE01"

# Threads we always want in the table (substring match on GetThreadDescription
# names); anything else above 10% of a core is listed too.
INTERESTING = ("CPU thread", "Video", "VK submission", "Emuthread")


def user_dir():
    """Fork UserDir: exe-adjacent User/ if portable.txt exists, else APPDATA.
    (Verified: no portable.txt next to the fork exe; logs are in APPDATA.)"""
    exe_dir = os.path.dirname(DOLPHIN_EXE)
    if os.path.exists(os.path.join(exe_dir, "portable.txt")):
        return os.path.join(exe_dir, "User")
    return os.path.join(os.environ["APPDATA"], "Dolphin Emulator")


# --- parsing (pure, selftest-able) -------------------------------------------
def parse_times(path):
    """Read a render_times/vblank_times file -> list of per-frame intervals (ms)."""
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(float(line))
            except ValueError:
                pass  # tolerate a torn last line from a hard kill
    return out


def tail_slice(intervals, tail_seconds):
    """Last N seconds of intervals, walking backwards by cumulative time."""
    budget = tail_seconds * 1000.0
    total = 0.0
    i = len(intervals)
    while i > 0 and total < budget:
        i -= 1
        total += intervals[i]
    return intervals[i:]


def percentile(sorted_vals, q):
    """Nearest-rank on a pre-sorted list; q in [0,1]."""
    if not sorted_vals:
        return float("nan")
    idx = round((len(sorted_vals) - 1) * q)
    return sorted_vals[idx]


def stats(intervals, tail_seconds):
    """-> dict: n, span_s, hz (mean over tail), p1/p50/p99 interval ms."""
    tail = tail_slice(intervals, tail_seconds)
    if not tail:
        return {"n": 0, "span_s": 0.0, "hz": float("nan"),
                "p1": float("nan"), "p50": float("nan"), "p99": float("nan")}
    s = sum(tail)
    srt = sorted(tail)
    return {
        "n": len(tail),
        "span_s": s / 1000.0,
        "hz": 1000.0 * len(tail) / s,
        "p1": percentile(srt, 0.01),
        "p50": percentile(srt, 0.50),
        "p99": percentile(srt, 0.99),
    }


# --- INI peeking (read-only; we never write to APPDATA) -----------------------
def ini_get(path, section, key):
    """Minimal INI read: value of key under [section], or None."""
    if not os.path.exists(path):
        return None
    cur = None
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    cur = line[1:-1].lower()
                elif "=" in line and cur == section.lower():
                    k, _, v = line.partition("=")
                    if k.strip().lower() == key.lower():
                        return v.strip()
    except OSError:
        return None
    return None


def effective_speed(udir):
    """Report EmulationSpeed from both files; per-game wins (HANDOFF-PC §1)."""
    per_game = ini_get(os.path.join(udir, "GameSettings", GAME_ID + ".ini"),
                       "Core", "EmulationSpeed")
    global_ = ini_get(os.path.join(udir, "Config", "Dolphin.ini"),
                      "Core", "EmulationSpeed")
    eff = per_game if per_game is not None else global_
    return eff, per_game, global_


# --- host thread CPU% by name (from pcprofile.py) -----------------------------
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
THREAD_QUERY = 0x0040 | 0x0800  # QUERY_INFORMATION | QUERY_LIMITED
k32.GetThreadDescription = ctypes.WINFUNCTYPE(
    ctypes.c_long, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p))(
    ("GetThreadDescription", k32))


class FT(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


def ft2s(ft):
    return ((ft.hi << 32) | ft.lo) / 1e7


def thread_times(pid):
    """{tid: (name, kernel+user seconds)} for all threads of pid."""
    TH32CS_SNAPTHREAD = 0x4

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD),
                    ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD)]

    out = {}
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(THREADENTRY32)
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            h = k32.OpenThread(THREAD_QUERY, False, te.th32ThreadID)
            if h:
                c, e, kt, ut = FT(), FT(), FT(), FT()
                if k32.GetThreadTimes(h, ctypes.byref(c), ctypes.byref(e),
                                      ctypes.byref(kt), ctypes.byref(ut)):
                    name = ctypes.c_wchar_p()
                    k32.GetThreadDescription(h, ctypes.byref(name))
                    out[te.th32ThreadID] = (name.value or f"tid{te.th32ThreadID}",
                                            ft2s(kt) + ft2s(ut))
                k32.CloseHandle(h)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return out


def thread_table(t0, t1, window_s):
    """Rows (pct_of_core, name) sorted hot-first; interesting names always kept."""
    rows = []
    for tid, (name, tt1) in t1.items():
        dt = tt1 - t0.get(tid, (name, 0.0))[1]
        pct = 100.0 * dt / window_s
        keep = pct >= 10.0 or any(s.lower() in name.lower() for s in INTERESTING)
        if keep and pct >= 0.5:
            rows.append((pct, name))
    return sorted(rows, reverse=True)


# --- process guard ------------------------------------------------------------
def dolphin_running():
    """True if any Dolphin.exe is alive. We NEVER kill a pre-existing one."""
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Dolphin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True).stdout
    return "Dolphin.exe" in out


# --- selftest -----------------------------------------------------------------
def selftest():
    """Fabricate synthetic times files and verify the parser math. No launch."""
    import tempfile
    ok = True

    def check(label, got, want, eps=1e-6):
        nonlocal ok
        good = abs(got - want) <= eps
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: got {got!r}, want {want!r}")

    with tempfile.TemporaryDirectory() as td:
        # Test 1: 60s of 10ms (cold cache stand-in) then exactly 30s of 4ms.
        # tail(30s) must select ONLY the 4ms frames -> 250.0 Hz flat.
        p = os.path.join(td, "t1.txt")
        with open(p, "w") as f:
            f.write("10.00000000\n" * 6000)
            f.write("4.00000000\n" * 7500)
            f.write("garbage-torn-line")  # hard-kill tolerance
        iv = parse_times(p)
        check("parse count (torn line dropped)", len(iv), 13500)
        st = stats(iv, 30)
        check("tail n", st["n"], 7500)
        check("tail span s", st["span_s"], 30.0)
        check("mean Hz", st["hz"], 250.0)
        check("p1 ms", st["p1"], 4.0)
        check("p50 ms", st["p50"], 4.0)
        check("p99 ms", st["p99"], 4.0)

        # Test 2: intervals 1..100 ms, tail bigger than the file -> uses all.
        p2 = os.path.join(td, "t2.txt")
        with open(p2, "w") as f:
            for v in range(1, 101):
                f.write(f"{v}.0\n")
        iv2 = parse_times(p2)
        st2 = stats(iv2, 9999)
        check("all-file n", st2["n"], 100)
        check("mean Hz (1000*100/5050)", st2["hz"], 1000.0 * 100 / 5050, 1e-9)
        check("p1 (nearest rank)", st2["p1"], 2.0)
        check("p50 (nearest rank)", st2["p50"], 51.0)
        check("p99 (nearest rank)", st2["p99"], 99.0)

        # Test 3: tail boundary lands mid-file, partial frame included.
        iv3 = [100.0, 100.0, 100.0]  # tail 0.25s -> needs 250ms -> 3 frames
        st3 = stats(iv3, 0.25)
        check("boundary includes crossing frame", st3["n"], 3)

    print("SELFTEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


# --- the run ------------------------------------------------------------------
def resolve_savestate(arg, udir):
    if arg.isdigit():
        return os.path.join(udir, "StateSaves", f"{GAME_ID}.s{int(arg):02d}")
    return arg


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rom", default=DEFAULT_ROM)
    ap.add_argument("--savestate", help="path, or a slot number (e.g. 3 -> "
                    "StateSaves/GMSE01.s03). MUST be freshly made on the "
                    "current build+codes (HANDOFF-PC \u00a7S3.5).")
    ap.add_argument("--seconds", type=int, default=120,
                    help="run length; shader cache warms ~80s, keep >=90")
    ap.add_argument("--tail", type=int, default=30,
                    help="report the mean/percentiles of the LAST N seconds")
    ap.add_argument("--tag", default="untagged", help="label for bench-log.md")
    ap.add_argument("--selftest", action="store_true",
                    help="verify parser math on synthetic data; launches nothing")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if not args.savestate:
        ap.error("--savestate is required (path or slot number)")

    udir = user_dir()
    logs = os.path.join(udir, "Logs")
    render_f = os.path.join(logs, "render_times.txt")
    vblank_f = os.path.join(logs, "vblank_times.txt")
    state = resolve_savestate(args.savestate, udir)

    # -- preflight ------------------------------------------------------------
    if dolphin_running():
        print("REFUSING TO RUN: a Dolphin.exe process is already up (someone "
              "may be playing). Close it yourself and re-run. This script "
              "never kills a Dolphin it did not start.")
        sys.exit(2)
    for label, p in (("ROM", args.rom), ("savestate", state)):
        if not os.path.exists(p):
            print(f"ERROR: {label} not found: {p}")
            sys.exit(2)
    if ini_get(os.path.join(udir, "Config", "GFX.ini"),
               "Settings", "LogRenderTimeToFile") != "True":
        print(f"ERROR: LogRenderTimeToFile != True in {udir}\\Config\\GFX.ini "
              "— Dolphin will not write the times files. Enable it in the "
              "Dolphin UI (or the INI while Dolphin is closed) and re-run. "
              "This script does not edit APPDATA.")
        sys.exit(2)
    if args.seconds < 90:
        print(f"WARNING: --seconds {args.seconds} < 90; the shader cache "
              "warms for ~80s, this run will partly measure the cold cache.")

    print("*" * 74)
    print("* TRAP CHECK (HANDOFF-PC \u00a7S3.5): the savestate MUST be freshly "
          "made under")
    print("* the CURRENT build + Gecko config. An old state silently restores "
          "stale")
    print("* in-game code state (G value), invalidating all SPEED conclusions.")
    st_m = datetime.datetime.fromtimestamp(os.path.getmtime(state))
    exe_m = datetime.datetime.fromtimestamp(os.path.getmtime(DOLPHIN_EXE))
    print(f"*   savestate mtime : {st_m:%Y-%m-%d %H:%M}   ({state})")
    print(f"*   Dolphin.exe mtime: {exe_m:%Y-%m-%d %H:%M}")
    if st_m < exe_m:
        print("*   >>> savestate is OLDER than the binary: it will not load "
              "(build-locked)")
        print("*   >>> or worse, poison the run. Make a fresh state first.")
    print("*" * 74)

    eff, per_game, global_ = effective_speed(udir)
    print(f"EmulationSpeed: per-game={per_game}  global={global_}  "
          f"-> effective={eff} (per-game wins, HANDOFF-PC \u00a71)")
    print("Reminder: check for background load (HANDOFF-PC \u00a77 — a session "
          "was wasted benchmarking under Palworld).")

    pre_mtime = os.path.getmtime(render_f) if os.path.exists(render_f) else 0

    # -- launch -----------------------------------------------------------------
    cmd = [DOLPHIN_EXE, "-e", args.rom, "-s", state, "-b"]
    print(f"\nLaunching: {subprocess.list2cmdline(cmd)}")
    t_start = time.time()
    proc = subprocess.Popen(cmd)

    tail_start = args.seconds - args.tail
    deadline = t_start + args.seconds
    print(f"Running {args.seconds}s (thread sampling over the last "
          f"{args.tail}s)...")
    while time.time() < t_start + tail_start:
        if proc.poll() is not None:
            print("ERROR: Dolphin exited early (bad savestate / build "
                  "mismatch?). Aborting.")
            sys.exit(1)
        time.sleep(1)
    t0_threads = thread_times(proc.pid)
    t0_wall = time.time()
    while time.time() < deadline:
        if proc.poll() is not None:
            print("ERROR: Dolphin exited early during the tail window. Aborting.")
            sys.exit(1)
        time.sleep(0.5)
    t1_threads = thread_times(proc.pid)
    window_s = time.time() - t0_wall

    # -- graceful close (WM_CLOSE via taskkill WITHOUT /F, so the emu shuts
    #    down cleanly and finalizes the times files) ---------------------------
    print("Closing Dolphin gracefully (taskkill, no /F)...")
    subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        print("WARNING: graceful close timed out after 30s; forcing (/F). "
              "The tail of the times files may be truncated.")
        subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)],
                       capture_output=True)
        proc.wait(timeout=10)
    time.sleep(2)  # let the filesystem settle

    # -- parse ------------------------------------------------------------------
    if not os.path.exists(render_f) or os.path.getmtime(render_f) <= pre_mtime:
        print(f"ERROR: {render_f} was not rewritten by this run. Nothing to "
              "parse (LogRenderTimeToFile off, or the run never rendered).")
        sys.exit(1)
    r = stats(parse_times(render_f), args.tail)
    v = stats(parse_times(vblank_f), args.tail)
    threads = thread_table(t0_threads, t1_threads, window_s)

    # -- report -----------------------------------------------------------------
    now = datetime.datetime.now()
    lines = []
    lines.append(f"### bench {now:%Y-%m-%d %H:%M} — {args.tag}")
    lines.append(f"- cmd: `-e <rom> -s {os.path.basename(state)} -b`, "
                 f"{args.seconds}s run, stats = last {args.tail}s "
                 f"(warm; cache warms ~80s)")
    lines.append(f"- EmulationSpeed: effective **{eff}** "
                 f"(per-game {per_game} / global {global_})")
    lines.append(f"- FPS (render): **{r['hz']:.1f}** mean | intervals ms "
                 f"p1 {r['p1']:.2f} / p50 {r['p50']:.2f} / p99 {r['p99']:.2f} "
                 f"| n={r['n']}")
    lines.append(f"- VPS (vblank): **{v['hz']:.1f}** mean | intervals ms "
                 f"p1 {v['p1']:.2f} / p50 {v['p50']:.2f} / p99 {v['p99']:.2f} "
                 f"| n={v['n']}")
    lines.append(f"- threads (% of one core over the tail window):")
    for pct, name in threads:
        lines.append(f"    - {name}: {pct:.1f}%")
    lines.append(f"- savestate: {state} (mtime {st_m:%Y-%m-%d %H:%M}; "
                 f"S3.5 freshness is on you)")
    block = "\n".join(lines)

    print("\n" + "=" * 74)
    print(block)
    print("=" * 74)

    with open(BENCH_LOG, "a", encoding="utf-8") as f:
        f.write(block + "\n\n")
    print(f"\nAppended to {BENCH_LOG}")


if __name__ == "__main__":
    main()
