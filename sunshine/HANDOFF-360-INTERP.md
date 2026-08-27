# HANDOFF — 360Hz ON THE DESKTOP (interp pacer, session 2026-08-27)

**Written:** 2026-08-27 evening, PC session. **Branch:** `fpspatch-generalize`.
**Read alongside:** `HOWTO-INTERPOLATION-360.md` (background + original design),
`SYNC-240.md` (2026-08-27 PC entries), `HANDOFF-ONLINE-PAIRING.md` (the other
open thread: PC solo ghost test → Mac joins).

## Where the user left it

> "WOW THIS IS RUNNING WAY BETTER!!!!!! … it's stable. hand off to next chat
> for us to go at 360fps."

Interp mode (`play360interp.ps1`, 180 logic × 2-blend) is running **flat 180
logic at correct speed everywhere, Bianco included, user-confirmed stable**.
That was the session's goal — but the *pacing* story is not finished (below),
so "true 360" still has one open question.

## Machine state (exact, verify before trusting)

- Primary checkout: `C:\code\high-fps-sunshine` (the old `C:\code\high-fps-dolphin`
  is a husk — all gitignored state was MOVED). Remote: `2-X/high-fps-sunshine`.
- **Running/stable exe**: `dolphin-src\Binary\x64\Dolphin.exe` (mtime 2026-08-27
  18:39) = **pacer v2.5** (dolphin-src commit `ca3bcac` + the slack-cap edit that
  became part of `3803d10`'s history — see version ladder below).
- **Untested v3 exe**: `dolphin-src\Build\x64\Release\Dolphin\bin\Dolphin.exe`
  (mtime 18:43) = dolphin-src HEAD `3803d10`. **Swap it into Binary\x64 (Dolphin
  closed!) to A/B.** The committed distribution patch matches v3, not the
  running v2.5.
- `GFX.ini [Settings] HiFpsNonBlockingReadbacks = True` is live (and in
  GFX.ini.pc). Fork switch from commit `0511772`; default False.
- BSMSO server verified running on Windows ("listening on TCP+UDP port 27015");
  `smslaunch` can now host on WIN. Firewall inbound 27015 still NOT allowed —
  Kris action.
- Build system: MSBuild at `C:\Program Files (x86)\Microsoft Visual Studio\2022\
  BuildTools\MSBuild\Current\Bin\MSBuild.exe` (vswhere reports NOTHING — don't
  trust it). Build `Source\dolphin-emu.sln` or just `Source\Core\DolphinQt\
  DolphinQt.vcxproj`, Release x64. The final Binary copy fails while Dolphin
  runs — copy by hand after quitting it.

## The pacer version ladder (all in `Present.cpp::PresentInterpolatedSubframes`)

| ver | behavior | verdict |
|---|---|---|
| v1 (0511772) | sleep `est*i/K` BEFORE presenting the blend; floor-tracked est | blend+real bunched (blend ~0 screen time); est fixed point = 2× work → **sagged to ~122-160 with host idle** (the 2026-08-20 "5.6→10.9ms" bug, still alive) |
| v2 (ca3bcac) | present blend FIRST, sleep between blend and real present; subtract measured injected sleep from est | Delfino flat 180 (VPS p1/p50/p99 5.51/5.56/5.61) but **Bianco dips to 160**: sleep = est/2 stalls the video thread → heavy-scene period = 1.5×work |
| v2.5 (in 3803d10's diff, the RUNNING build) | cap sleep at slack = floor(raw) − est | **degenerate**: est drifts up to raw, slack→0, sleep→0. Result = flat 180 everywhere (user's "stable") but blend+real present **bunched** — effectively plain 180 with an invisible blend |
| v3 (3803d10 HEAD, **UNTESTED**) | no estimator: sleep to `min(base + floor(raw)*i/K, intended_present_time + 500µs)` — time before the frame's own deadline is free (normal `Present()` sleeps to it anyway), past it is stall | should give even cadence when healthy, zero slowdown when heavy. **Unknown**: how much earliness vs `intended_present_time` the video thread actually has at ViSwap — if ~0, v3 degenerates to v2.5's bunching (safe, but not paced) |

## Present-cadence tooling (added 2026-08-27 late session — READY, unrun)

PresentMon is ALREADY ON THIS MACHINE: NVIDIA FrameView SDK ships it at
`C:\Program Files\NVIDIA Corporation\FrameViewSDK\bin\PresentMon_x64.exe`
(PresentMon 2.x CLI; use `--v1_metrics` for the classic columns). ETW needs
admin — the shell is not elevated and "Performance Log Users" is empty, so a
capture costs ONE UAC click. **Do not trigger that while Kris is playing**
(secure-desktop focus steal = the game_io pause incident, UAC edition);
have Kris run it — the capture itself is passive, play continues through it.

- `research/scripts/pm_capture.ps1 [-Tag v25|-Tag v3] [-Seconds 60]` —
  self-elevating capture of the live Dolphin → `research/data/pm_<tag>.csv`,
  then auto-runs the analyzer.
- `research/scripts/present_cadence.py <csv>` — histograms msBetweenPresents +
  msBetweenDisplayChange and prints a verdict: BUNCHED (~0/5.6 alternating,
  blends dropped = v2.5 signature) vs EVEN (~2.8/2.8 = working v3). Tested
  against synthetic captures of both signatures.
- `research/scripts/swap_pacer.ps1 -To v3 | -To v25` — the A/B swap, refuses
  while Dolphin runs, keeps `Dolphin_v25_pacer.exe` backup for rollback.

## Next steps (in order)

1. **Capture v2.5 baseline while playing** (no restart needed): Kris runs
   `pm_capture.ps1 -Tag v25`, one UAC click, keeps playing 60s. Expected:
   BUNCHED verdict (confirms the v2.5 degenerate analysis with data).
2. **A/B v3**: quit Dolphin, `swap_pacer.ps1 -To v3`, run `play360interp.ps1`,
   play Delfino AND Bianco. `live_bench.py --seconds 90` must stay flat
   (VPS p99 ≈ 5.6ms); user feel-check for dips; `pm_capture.ps1 -Tag v3`
   for the cadence verdict. Roll back any time with `swap_pacer.ps1 -To v25`.
   If v3 still bunches (no earliness at ViSwap), the real fix is
   the **present-pacer thread** (render blends into a small ring of scratch
   textures on the video thread; a dedicated thread owns PresentBackbuffer
   timing — `m_swap_mutex` already guards presents). That is the Route-B
   "decouple present-rate from VI" heart, sketched in HOWTO-INTERPOLATION-360.
3. **Ghosting verdict**: linear crossfade on fast pans/spins — user never
   explicitly judged it. If visible, options: shorter blend t (asymmetric
   weights), or motion-vector reprojection (big).
4. **120×3 fallback** if 180×2 disappoints anywhere: `DOLPHIN_FRAME_INTERP=3`
   + apply an Offline 120 profile (EmulationSpeed 2.0) — 120 logic is
   bulletproof everywhere and 3×120 = 360 presents. Sleep budget math is the
   same; v3's deadline bound applies unchanged.
5. **Then the online pairing** (HANDOFF-ONLINE-PAIRING.md): PC solo ghost
   test → SYNC post → Mac joins `192.168.1.20:27015`, both at 120 → PC to 240.
   Server + launcher hosting are DONE; blockers left: firewall allow +
   somebody in a stage on both machines.

## Measured numbers from this session (peek gate live everywhere)

- Native 6.0x unthrottled, live play: Plaza ~350-355 VPS, shine-select 359.6,
  **Bianco 315-317** (was ~170 pre-peek-gate). 0x5555 affinity: no effect.
- Interp 180×2 v2 (60s live): 179.8 mean, VPS p1/p50/p99 = 5.51/5.56/5.61 ms,
  CPU 27% / Video 18% of a core.
- Interp 180×2 v2.5 (90s live incl. Bianco): 179.2 mean, p99 5.60 ms.

## Tooling added this session (committed)

- `sunshine/research/scripts/live_bench.py` — passive 60-90s VPS + per-thread
  CPU sampling of LIVE play (no savestate, never touches input). Imports
  benchmark.py's parsers.
- `sunshine/launcher/drive_launcher.py` — headless `apply()`+`launch()` of a
  named profile (`python drive_launcher.py "Offline 360" [--fps N] [--apply-only]`).
- `sunshine/research/scripts/game_io.ps1` — focus/screenshot/keystroke helper
  for the Dolphin window (A = SPACE via the DInput keyboard binding).
  **NEVER send keys while the user is playing** — it paused their game once.
