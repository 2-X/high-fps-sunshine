# Gelato "The Sand Bird Is Born" — bird flies very slow at 120fps

Reported 2026-08-28: on the sand-bird level, the giant bird's flight velocity is
**"sooo slow"** (Mario/everything else normal → bird-specific, not a perf drop).

## Static RE done (pristine NTSC-U main.dol, us.map)
- `TSandBird` symbols: `__ct__=0x801CF9D0`, `initMapObj__=0x801CFAA4`,
  `control__=0x801CFBFC`, `__vt__9TSandBird=0x803CF2B4`.
- **`control__9TSandBird` is NOT the flight.** Full disasm (0x801CFBFC..0x801CFE3C):
  it only does per-frame joint-coin update (`control__10TJointCoin`), two SE gate/plays
  (0x217c/0x217d), sand particle emits (0x159/0x15a) on joints, a demo-camera check, and
  the shine appear/disappear balloon gated on a countdown at `+0x104(this)` (starts 0x960).
  **No framerate-global (`-0x3E8(r2)` / 0x804167B8) reference anywhere.**
- `initMapObj__9TSandBird` only loads JPA particle resources (0x159/0x15a) + joint coins.
  No animation/rate setup here.
- ⇒ The bird's **flight is animation/actor-driven** (its model animation moves it, advanced
  by the generic actor path / possibly a level manager), NOT self-propelled in its own code.

## Hypothesis (needs live confirmation)
"Very very slow" ≈ quarter/half speed = an **over-corrected animation rate** on the bird's
flight animation. Directly relevant: the OPEN QUESTION in [[sunshine-fpspatch-generator]] —
at 120fps the anim-rate divisor should be constant 4 vs 2G, and CalcAnim-path assumptions.
If the bird's flight animation is on a path where the anim-rate fix (SMSGetAnmFrameRate→0.5,
0x802A7BD8) is double-applied or mis-scaled, it plays ~1/4 speed. Alternatively the bird uses
`setFrameRate__6MActor` (0x80238E7C) with a custom rate that interacts badly with the sim
substep. Not yet pinned — the bird's own code has no rate logic, so it's in the shared
actor-animation path for THIS animation.

## Decisive next step — measure the bird LIVE (recipe ready)
When on **Gelato Beach Ep 3** with the bird spawned, run the scanner (built, works via
`mac-online` memhelper): scan MEM1 for objects whose `+0 == 0x803CF2B4` (TSandBird vtable) →
that's the bird. Then:
1. Sample `bird+0x10` (LiveActor mPosition, 3×f32 BE) over ~0.5s → measured world speed.
   Compare to a 60fps reference to get the exact slow factor (½? ¼?).
2. Read the bird's MActor + its `J3DFrameCtrl` rate (find the MActor ptr offset live; the
   frame-ctrl rate field reveals whether it's 0.5 (correct), 0.25 (double-corrected), or 1.0).
The slow-factor + the frame-ctrl rate together pin the fix: a C2 Gecko code that sets the
bird's animation rate correctly (like the other high-fps anim-rate fixes), scaled with G.

## Status
Static RE complete; **fix blocked on one live measurement** on that level. Not a guess-and-ship
— get the live number first, then one targeted C2. Sibling bug (Ricco Blooper surf speed +
reversed lean) is being handled separately → `HANDOFF-BLOOPER-SURF.md`.
