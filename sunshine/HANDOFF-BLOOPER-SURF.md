# HANDOFF — Ricco Harbor Blooper-surfing (BUG 1 speed, BUG 2 reversed lean)

Target: BSMSO online build, **GMSE01 NTSC-U**. Binary disassembled:
`/Applications/gamecube/bsmso-work/pristine-root/root/sys/main.dol` (vanilla, unmodified by BSMSO).
Map: `sunshine/bsmso/bse-fork/maps/us.map`. SDA verified: **r2 = 0x80416BA0** (framerate global
0x804167B8 = -0x3E8(r2)). All addresses below are static VAs in that DOL.

## TL;DR

- **BUG 1 (surf speed)** — REAL and framerate-related. The whole surf physics lives in
  `TMario::doSurfing` (0x8025B434), NOT in `TSurfGesso`. `TSurfGesso::perform` (0x80047DA8) just
  delegates to `TSmallEnemy::perform`; the Blooper is a passive rideable. `doSurfing` is a raw
  per-tick Euler integrator with **hard-coded** speed increments and **no `SMSGetAnmFrameRate`
  self-scaling** — so it is not in the class that the existing anim-rate/animal-speed fixes touch.
  Root-cause instruction range and the exact constants are below, with two candidate C2 fixes.
  Confidence the mechanism is in `doSurfing`: **high**. Confidence on which of the two fixes is
  correct: **medium** — needs one in-game A/B (see "Validation").

- **BUG 2 (reversed lean)** — **NOT a high-fps bug.** A framerate factor G = FPS/60 is a positive
  scalar; it can change a rotation's *magnitude* but can never *flip its sign*. A reversed lean is a
  sign/mirror inversion and is therefore pre-existing (vanilla or a BSE-moveset asset issue), present
  at 60fps too. **`isMarioLeanMirror` (0x80028E74) is a red herring** — proof below. Do not spend
  high-fps effort here; it is an animation-asset / body-roll sign issue to be confirmed with a live
  memory watch, not a Gecko rate fix.

---

## Symbols (verified)

```
perform__10TSurfGessoFUlPQ26JDrama9TGraphics   0x80047DA8   (delegates to TSmallEnemy::perform)
surfing__6TMarioFv                             0x8025A0F4   (surf state execute)
doSurfing__6TMarioFv                           0x8025B434   (** speed + steer integrator **)
slopeProcess__6TMarioFv                        0x8025BB64   (heading->velocity; SHARED by many states)
walkProcess__6TMarioFv                         0x802570C4   (velocity->position integrator; SHARED)
getSurfingParamsWater__6TMarioFv               0x8025B844
__ct__Q26TMario14TSurfingParamsFPCc            0x80273A70   (param defaults)
IConverge__Fiiii                               0x8022B0DC   (integer converge)
isMarioLeanMirror__16TCameraMarioDataCFv       0x80028E74   (camera-only; see BUG 2)
MarioWaistCtrl__FP7J3DNodei                    0x802488A4   (waist-roll joint callback)
```

`TSurfingParams` layout (from the ctor at 0x80273A70; single ctor, all three difficulty blocks share
these defaults). Field = value-float offset within the param block; three blocks live in TMario at
0x1648/0x19f0/0x1d98 (in-water) and 0x181c/0x1bc4/0x1f6c (on-ground), selected by TMario+0x389
(difficulty 0/1/2):

```
+0x18  mRotMin     = 2048.0
+0x2c  mRotMax     = 1024.0
+0x40  mPowMin     = 24.0
+0x54  mPowMax     = 64.0
+0x68  mAccel      = 58.0
+0x7c  mWaistRoll  = 0.25     <- body-roll amount (the LEAN)
+0x90  mWaistPitch = 170.0
+0xa4  mWaistRollMax = 0x400  (short)
+0xb8  (short)       = 0x1555
```

Relevant TMario fields:
```
+0x8c  surf power input (signed, stick-derived; magnitude of forward push)
+0x90  mDir   = camera-relative target heading (set in checkController__6TMario @0x80251de0)
+0x96  mTurn  = smoothed applied heading (IConverge target; generic Mario turn field)
+0xb0  mSurfSpeed (** the frame-tied scalar **)
+0xa4/+0xac = mVelX / mVelZ (written by slopeProcess, consumed by walkProcess)
```

---

## BUG 1 — surf speed. Root cause: `doSurfing` per-tick Euler integrator

Disasm of the speed block (0x8025B638–0x8025B784), constants resolved:

```
8025b638  lfs   f1, -0xe08(r2)      ; f1 = 2.0
8025b63c  lfs   f0, 0x8c(r31)       ; f0 = surf power input
8025b640  fmuls f0, f1, f0          ; f0 = 2.0 * input
8025b644  fcmpo f0, f7(mPowMax=64)  ; clamp high
8025b650  fmr   f3, f7
8025b654  fcmpo f3, f6(mPowMin=24)  ; clamp low
8025b65c  fmr   f3, f6              ; f3 = P = clamp(2*input, 24, 64)   (target speed)
8025b660  lfs   f2, 0xb0(r31)       ; f2 = mSurfSpeed
--- if mSurfSpeed == 0:            (kickstart)
8025b674  lfs   f0, -0xe04(r2)      ; 1.1
8025b678  fadds f0, f2, f0          ; mSurfSpeed += 1.1
--- else if mSurfSpeed <= P:       (accelerate toward P)
8025b73c  lfs   f0, 0x68(r3)        ; mAccel = 58
8025b740  fdivs f0, f2, f0          ; mSurfSpeed / 58
8025b744  lfs   f1, -0xe04(r2)      ; 1.1
8025b74c  fsubs f0, f1, f0          ; 1.1 - mSurfSpeed/58
8025b750  fadds f0, f2, f0          ; mSurfSpeed += (1.1 - mSurfSpeed/58)
--- else (mSurfSpeed > P):         (decelerate)
8025b774  lfs   f0, -0xe9c(r2)      ; 1.0
8025b778  fsubs f0, f2, f0          ; mSurfSpeed -= 1.0
--- clamp:
8025b784  fcmpo mSurfSpeed, f7(mPowMax) ; if > mPowMax -> = mPowMax
```

Then the steering (0x8025B790–0x8025B7D8) converges `mDir - mTurn` toward 0 by an integer step
`rotStep = mRotMin + t*(mRotMax-mRotMin)`, `t = (P-mPowMin)/(mPowMax-mPowMin)`, via `IConverge`, and
writes `mTurn = mDir - IConverge(...)`. `slopeProcess` (called at 0x8025B7E0) then turns
`mSurfSpeed` × sin/cos(mTurn) into `mVelX/mVelZ` (0xa4/0xac), and `walkProcess` integrates
`pos += mVel * 0.25 * actorSpeedFactor`.

**Why it's frame-tied:** the increments (`+1.1`, `1.1 - mSurfSpeed/58`, `-1.0`) and the `IConverge`
step are applied **once per `doSurfing` call with fixed magnitudes and no dt / no
`SMSGetAnmFrameRate` term.** `surfing` calls `doSurfing` unconditionally every Mario update
(0x8025A170, no gate). If the surf state advances on the 120 Hz-pinned tick (the same class as the
animal-movement sites the bundle already ×4-restores), then per wall-clock second the integrator runs
2× as often: acceleration and the `-1.0` deceleration are 2× faster, and — depending on where the
surf position update actually lands relative to the sim's dt handling — the travel speed is up to 2×
off versus 60fps. This is the canonical fixed-increment high-fps velocity bug.

Note: the *steady-state* speed `mSurfSpeed* = 1.1·58 = 63.8 ≈ mPowMax` is a tick-rate-independent
fixed point, so the top speed is roughly preserved; the audible/visible error is dominated by the 2×
acceleration/decel responsiveness and by the per-tick `IConverge` making steering 2× snappier.

### Proposed C2 fixes (pick after the in-game A/B in "Validation")

House style: constant, G-independent (the sim is pinned ~120 Hz at every G — see
`fpspatch.py` header and the boid/particle-parity gates). Both options below are CONSTANT.

**Fix A (preferred — gate the whole integrator to every other tick).** Cleanest: also fixes the 2×
steering snappiness and 2× anim advance in one hook, mirrors the `boid_gate` substep-parity pattern.
Hook `surfing__6TMario`'s call to `doSurfing` (0x8025A170, orig `480012C5 bl doSurfing`): only call
`doSurfing` on even substeps of `gpMarDirector+0x5C` (the substep counter used by `boid_gate`, see
`fpspatch.py` `LWZ_UNK5C`/parity helper); on odd substeps skip `doSurfing` but still run
`walkProcess` so position advances on the last-computed velocity. This makes accel/steer/anim all
tick at native 60 Hz while position still integrates every substep (so motion stays smooth). This
requires a small C2 that reads the parity and conditionally executes the `bl`.

**Fix B (surgical — halve the per-tick speed increments).** If a full every-other-tick gate is
undesirable, scale only the three increments so accel/decel deliver the 60fps per-tick amount:
- 0x8025B674 kickstart 1.1 → 0.55
- 0x8025B750 `mSurfSpeed += (1.1 - mSurfSpeed/58)` → `mSurfSpeed += 0.5*(1.1 - mSurfSpeed/58)`
- 0x8025B778 decel `-1.0` → `-0.5`
These halve the transient rates; the fixed point 63.8 is unchanged (correct — top speed already
matched 60fps). This does NOT touch the 2× `IConverge` steering snappiness.

Do NOT scale in `slopeProcess` or `walkProcess`: both are SHARED by normal walk/run/turn/jump states
(callers of slopeProcess: moveMain, doRunning, turnning, jumpSlipCommon, fireDashing, loserDown,
downingCommon — 0x8025BB64 caller scan), so a ×0.5 there would break all ground movement.

`getSurfingParamsWater` is called only by `surfingEffect` (spray particles) in main.dol — editing the
param defaults would not reach the speed math and is the wrong lever.

---

## BUG 2 — reversed lean. NOT high-fps. `isMarioLeanMirror` is a red herring.

### Why `isMarioLeanMirror` is unrelated (verified)
- It has exactly **one** caller: `CPolarSubCamera::execCameraModeChangeProc` @0x8002178C
  (bl-scan of 0x80028E74). It is a **camera-mode selector**, not a body/animation predicate.
- Its body (0x80028E74–0x80028ECC): returns 1 only when Mario's ground plane has surface-attribute
  code **0xCF** (`SMS_GetMarioGrPlane`; `addis r0,r3,-0x4000; cmplwi r0,0xcf`). When true, the camera
  picks preset mode **0xB** (0x80021798). That is a wall/lean *camera* case.
- The Blooper surfs on **water** — every water check in `doSurfing` uses surface codes
  0x100/0x101/0x102..0x105/0x4104 (e.g. 0x8025B468–0x8025B494), never 0xCF. So `isMarioLeanMirror`
  never fires during surfing and cannot mirror the surf lean.

### Where the lean actually is, and why the sign can't be a high-fps artifact
The visible lean is the **waist roll** applied by `MarioWaistCtrl__FP7J3DNodei` (0x802488A4), a
J3DNode joint callback that builds a rotation from a signed roll angle (reads gpMario / a
controller-work global at `-0x7118(r13)`, `lha 0xa4`, and a pitch at node+4; `neg`/euler build at
0x802488E8–0x80248960). The roll **direction** is the sign of that angle, seeded from the turn.
Steering itself is correct in shared code: the surf heading `mDir` (0x90) is produced by the SAME
`checkController__6TMario` path (matan2 of the camera-relative stick vector, 0x80251DC8–0x80251DE0)
that walking/running use, and those steer correctly — so the *travel* direction is right; only the
*body roll* is mirrored.

A framerate factor G is a positive multiplier applied to rates/steps. It scales magnitudes; it has no
sign. A "leans right when turning left" symptom is a sign inversion, so it is **present at 60fps too**
and is pre-existing — either a vanilla body-roll sign or, more likely for this build, a
**mirrored/left-handed surf animation asset in the BSE moveset** (the report "looks mirrored/skewed"
fits a mirrored .bck/.bas or a negated roll term). This is out of scope for the high-fps Gecko bundle.

### To pinpoint BUG 2 for a fix (not a rate fix)
Live-watch, while surfing, the signed roll angle the body uses — the `lha 0xa4` source in
`MarioWaistCtrl` (resolve `-0x7118(r13)` at runtime; it is a BSS Mario/controller global, zero in the
static image so it can't be resolved statically). Confirm its sign vs stick direction. If the angle's
sign matches the stick but the model tilts opposite, it's a mirrored animation asset; if the angle's
sign is itself opposite the intended lean, it's a one-word `fneg`/negate to add at the roll write.
Either way it is a single sign flip, not a Gecko rate code.

---

## Validation needed on-console
1. **BUG 1 direction & magnitude:** at 120fps, measure surf top speed and time-to-top-speed vs a
   60fps reference (or vs walking, which is correctly paced). If travel is ~2× fast → apply Fix A
   (preferred) or Fix B and re-measure; Fix A additionally normalizes steering snappiness. If travel
   speed already matches 60fps and only *steering feel* is off, the position path is dt-aware and the
   real fix is only the `IConverge` step (halve rotStep at 0x8025B7C4/0x8025B7C8) — that is the one
   fact I could not settle statically (Mario-update cadence vs substep dt).
2. **BUG 2:** confirm the roll-angle sign with a memory watch as above; then flip the sign in the
   body-roll asset or add a single negate. No rate scaling.

## Confidence
- Surf physics is entirely in `TMario::doSurfing`, constants and integrator as decoded above: **high**
  (full disasm, all SDA constants resolved, callers verified).
- BUG 1 is frame-tied (fixed-increment integrator, no dt/no anim-rate stub): **high** on mechanism;
  **medium** on the exact ×0.5-vs-every-other-tick choice and on whether the visible error is travel
  speed or steering feel — one in-game A/B resolves it. The unresolved variable is the surf-state
  update cadence relative to the sim's position-dt handling (0.25 constant in walkProcess @0x8025B711F
  is fixed, not the framerate global).
- BUG 2 is NOT high-fps and `isMarioLeanMirror` is unrelated: **high** (single camera-only caller,
  0xCF surface gate, water never hits it; sign can't come from a positive G).
