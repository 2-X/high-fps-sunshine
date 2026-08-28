# Windows: a bug-free 60 fps online (BSMSO) — handoff for Aaron's PC

Written 2026-08-28 for the Windows player who wants **60 fps that is actually
correct**, not the "known-good 60 fps ISO" that still carries high-fps bugs.
If you are the Claude on Aaron's machine reading this: your job is the install +
verify steps at the bottom. The context above them is so you can debug if a
step misbehaves.

## Why the "known-good 60 fps ISO" is still buggy

Super Mario Sunshine's game logic is **native 30 fps**. BSMSO's "60 fps" mode
(BSE `FPS_60`) runs the engine at **2x** that. So the 60 fps ISO carries the
same *class* of high-fps bugs the 120 fps kit fixes — just at 2x magnitude
instead of 4x. Left unfixed at 60 you get, among others:

- boss/enemy animations playing ~2x fast (Petey's mouth/vomit window, Gooper),
- spray-spawned **blue coins vanishing ~2x too fast**,
- repeating sound effects (FLUDD hover, Noki rope creak, Gooper tentacles)
  chattering at 2x,
- the heat-haze shimmer pulsing 2x,
- the triple-jump chain window too tight,
- leaked HUD star sparkles after unpausing,
- Poink pigs self-destructing before they reach Petey,
- Noki Bay pollution readbacks running 2x too often.

These are exactly the frame-counted subsystems. The fix is the **BSE-60
companion Gecko bundle**, generated the same way as the 120/240 bundles.

## What 60 needs — and what it does NOT (this is the important part)

The companion is **not** the 120 bundle. Three things are different at 60, and
two of them matter for *correctness*, not just tidiness:

| Fix class | At FPS_120 | At FPS_60 | Why |
|---|---|---|---|
| Render-class gates (Noki, wipe, SE, EFB peek) | divisor 4 | **divisor 2** | render is 60 fps, native work is 30 Hz → gate 1-in-2 |
| anim-rate raw setters (Petey/Gooper etc.) | ×0.25 | **×0.5** | CALC_ANIM is 60 Hz at FPS_60, native 30 Hz → halve |
| Blue-coin / shimmer / bird / jump-chain | keep-1-of-4 / 0.25 / k2 / ×4 | **identical** | these are substep-paced, and the sim is 120 Hz at *both* rates |
| **Particle parity + boid flocking** | present | **OMITTED** | at FPS_60 CALC_ANIM already runs at native 60 Hz, so emitters are neither frozen nor doubled — adding the gate would **freeze or halve** particles |
| **Game-clock fix** | present | **OMITTED** | at FPS_60 `EmulationSpeed = 1` (real time), so race/countdown clocks are already correct |
| **Substep 120 Hz pin + input latch** | absent below 240 | **absent** | not needed at or below 120 |

The generator (`fpspatch.py --bse`) encodes all of this — do **not** hand-edit a
120 bundle down to 60. `bse_supported()`, `bse_parity()`, `bse_boid()` and
`bse_sim_fps()` were generalized for FPS_60 on 2026-08-28; `fpspatch.py 60
--bse --check` validates the result (and asserts the parity/boid/clock blocks
are absent).

## One big simplification vs 120: you probably don't need the custom Dolphin build

At 60 fps `EmulationSpeed = 1` (real time). The audio tempo/pitch bug is an
`EmulationSpeed > 1` artifact, so **at 60 the stock Dolphin audio is correct** —
no chipmunk, no binary DMA patch, no `AudioPreservePitch` needed. The custom
"kit" Dolphin build that 120 requires is therefore **not required for audio at
60**.

The one thing the custom build *also* carries is the Gecko capacity lift (stock
Dolphin silently stops running codes once the list fills). The BSE-60 companion
is small (~250 lines) and well under the stock cap, so for the companion alone
stock Dolphin is fine. If you stack a lot of *other* enabled codes on top and
something silently stops working, that cap is the first suspect (see verify log
below).

## Install + verify (do this)

You are pulling the same repo the Mac side uses; the Windows launcher already
understands 60.

**The one command** (regenerates the bundle fresh, installs force-codes, sets
`EmulationSpeed = 1`, boots, and proves the codes attached):

```powershell
powershell -ExecutionPolicy Bypass -File sunshine\bsmso\mac-online\play240.ps1 -Fps 60
```

Config-only, if you keep your own launch flow:

```powershell
python sunshine\bsmso\mac-online\switch_rate.py --fps 60
```

That path:
1. regenerates the **BSE-60 companion** from `fpspatch.py 60 --bse` (never reuse
   a stored bundle — stale bundles fail silently; the committed
   `research/codes/bse60-companion-v1.txt` is only a no-Python fallback),
2. installs the static codes (menu key-repeat scaled to 60 = 20/6 counts,
   DuneBud null-guard) and the boot-time `04` force-writes (BSE cold-boots at
   30 fps / 4:3 every launch, so `mFPSValue = 1` is forced),
3. sets `EmulationSpeed = 1.0` in both Dolphin.ini and the per-game INI,
4. boots and reads live memory to confirm the codes installed.

**REQUIRED companion — the J3D duplicate-entry guard.** The Noki pollution gate
is only safe with `$J3D duplicate-entry guard v2` enabled
(`research/codes/j3d-dup-entry-guard-v2.txt`). Without it, the gate can freeze
the Bianco Ep.1 intro. The launcher installs it; if you install by hand, do not
skip it.

**For online play:** MEM1 must be 64 MB (`RAMOverrideEnable = True`,
`MEM1Size = 0x04000000`) or the remote-puppet heap overruns and crashes.
`EnableCheats = True` globally **and** per-game. These are the same online
prerequisites as 120 — see `WINDOWS-120.md` §"Load-bearing gotchas" if anything
is off.

**Always read the verify log:** `%TEMP%\sms-verify.log` names every enabled code
that did NOT actually install. A silently-dead code list looks identical to a
working one in the Dolphin UI. Read this first if 60 feels wrong.

## Perf: if it dips (FLUDD spray, busy scenes)

At 60 the CPU/GPU budget is generous, but two things can drag it below 60 at
*every* rate (they are not rate bugs):

1. **Hot-path log flood.** BSMSO spams `[SMSO]`/`[BSMSO]` OSREPORT diagnostics.
   If Dolphin's `Config/Logger.ini` has `WriteToFile = True`, every line is a
   synchronous file write mid-emulation — heaviest during scene loads and
   FLUDD-heavy moments. Set **`WriteToFile = False`** (and delete a bloated
   `Logs/dolphin.log`). This was a measurable stall on the Mac test.
2. **Async shaders + warm cache** — `ShaderCompilationMode = 3` in the per-game
   INI, then play ~90 s to warm the cache before judging stutter.
3. **HD texture packs off** while chasing a stable 60; re-enable after.

(2)/(3) are the same knobs as `WINDOWS-120.md`; (1) is the one that most often
reads as "the game lags when FLUDD comes out."

## Verify checklist — everything below is NEEDS-TEST at 60

Nothing in the BSE-60 bundle has been in-game confirmed yet (the derivation is
sound and `--check` passes, but no one has booted FPS_60 with it). The reasoning
per fix is in `HIGH-FPS-CATALOG.md`; the FPS_60 cadence logic is in the
`fpspatch.py` docstrings for `bse_supported` / `bse_sim_fps` / `bse_parity`.
Boot FPS_60 and watch for:

- **Particles look normal** (this is the highest-risk call — the parity gate is
  deliberately omitted; if flames/sparkles/M-portal effects look **frozen or
  half-speed**, that assumption was wrong and the parity block needs to come
  back at 60 with a divisor-1 shape). Level-entry decompose/recompose should
  play at ~0.67 s, not a blink.
- **Blue coins** from a spray last ~20 s, not ~10.
- **Petey / Gooper** boss anims run at natural speed.
- **Repeating SEs** (FLUDD hover, Noki rope creak) sound like 30 fps, not fast.
- **Race/countdown clocks** tick at wall-clock speed (they should already be
  fine — the clock fix is intentionally omitted at 60).
- **Menus**: holding a direction repeats at a sane speed, not racing.
- **Bianco Ep.1 intro** does not freeze (J3D guard doing its job).

If any of these is wrong, capture which one and check it against the table
above and the catalog before changing codes — most likely culprits are the
parity omission (particles) or a divisor. Report back and the Mac side can
re-derive.

## Cross-play note

Sessions are position-synced, not lockstep, so 60 co-exists with players on 120
or 240 — nothing to coordinate. Aaron on a correct 60 and everyone else on
whatever they run.
