# BUG: jump chain (double/triple jump) window scales with the render rate under BSE

**Reported 2026-08-28 by John (120fps online client, fork disc, Radmin VPN join).**
**Status: FIXED — v2 shipped 2026-08-28 (see below). The rest of this file is
the original diagnosis, kept for the record.**

## RESOLUTION (2026-08-28, two rounds)

**v1 (231e53f):** C2 at the `lha r0,0(r4)` @0x80258D60 in TMario::jumpSlipEvents
scaling the loaded `rec->mMaxTimer` x4, BSE-guarded. Triple jump confirmed
working — but that lha serves EVERY JumpSlipRecord, and the same night's field
test (Kris, Online 120) found the collateral: a landing stun. The jumpSlip
dispatcher (prologue 0x80258308, r31 = 0x803DD1E0) passes SIX 20-byte records
at r31+0x38..+0x9C; x4 on all six restored vanilla-length landing/getup
recovery states that BSE's 120Hz status cadence had been shortening 4x — a
"snappiness" everyone had internalized as the high-fps feel.

**v2 (shipped):** `bse_jump_chain` in fpspatch now emits guarded DATA instead
of a hook — Gecko `20`-if on the framerate global (2.0f/4.0f per rate) + three
`02` halfword writes scaling ONLY the chain-feeding records:
0x803DD218/0x803DD22C (chain -> 0x02000881 double) and 0x803DD240 (-> 0x00000882
triple), 16 -> 64 ticks. Records +0x74/+0x88/+0x9C stay stock (short recovery
under BSE = desired feel; the verified double/triple A/B never used them).
Title: `$Jump-chain window x4 BSE-<fps> v2 (chain records only; NEEDS-TEST)`.
The v1 title is in switch_rate's STALE_TITLES (auto-removed on next run);
`--check` now REJECTS any C2 @0x80258D60. Client pickup: pull + rerun
switch_rate (it regenerates from fpspatch and purges v1). Field verdict wanted:
triple jump still easy AND no landing stun.

## Symptom

Double jump is very hard and triple jump is effectively impossible at BSE 120fps.
Everything else about the client is correct: solid 120fps, correct real-time speed,
correct-tempo audio, online sync working.

## The A/B (this is the whole finding)

Same disc, same controller, same session, only the BSE rate changed via
`switch_rate.py --fps N --aspect 3`:

| BSE rate | chaining a double/triple jump |
|---|---|
| 30 (native) | easy — vanilla feel |
| 60 | noticeably harder, still doable |
| 120 | cannot chain at all |

Monotonic and inversely proportional to the rate. That rules out input dropping
(which is threshold-like, not graded) and rules out the controller and the moveset,
neither of which changes with the rate.

## Reading

The chain window is a **raw tick counter consumed at the game's update rate**, with a
threshold constant tuned for the stock 30fps cadence. BSE raises the update rate without
scaling the constant, so the real-time window is `window30 / (fps/30)`:

- 60fps  → half the real-time window
- 120fps → a quarter — below human reaction time from the landing frame

This is the same class as **catalog #38 (menu key-repeat 4× under BSE)**: a
delay/interval constant correct in TICKS but consumed by a path BSE runs ungated at the
render rate. That one was fixed with `$Menu key-repeat BSE-120 v2` — an `slwi ×4` on
r5/r6 before `setButtonRepeat`, guarded on the `==2.0f` framerate literal.

The analogous fix here is to scale the chain-window threshold by G at the site where the
post-landing counter is compared, behind the same `==2.0f` guard so it is inert at other
rates. Suggested search: the landing/`mJumpCount` reset path in `TMario`'s per-frame
update — wherever the consecutive-jump counter is cleared on a timeout.

## Where to look (sharpened 2026-08-28)

`JUTGamePad::CButton::update` advances once per `read()`, and BSE runs `read()` **ungated
at 120Hz** (catalog #38, §38). Any counter downstream of it therefore runs 4x fast at
BSE-120. The observed 30/60/120 curve is precisely that shape.

The kit already assumes this is harmless outside menus, and that assumption is what this
bug contradicts:

- **#38's fix is deliberately narrow.** `$Menu key-repeat BSE-120 v2` scales `mRepeat`
  only (`slwi x4` on r5/r6 pre-`setButtonRepeat`); the catalog states outright
  "trigger/release edges untouched". Nothing else downstream of `read()` was scaled.
- **The one general read()-cadence tool is not emitted here.** `bse_select_gate()` hooks
  `read()`'s own entry (`BSE_READ_HOOK = 0x802A8054`, sole caller `bl @0x802A600C`) and
  zeroes all four pads' trigger words on non-tick frames. But it is scoped to the
  shine-select screen, and `fpspatch.py` documents: "At fps <= 120 nothing is emitted:
  the cadence is already 120 Hz (the select screen was always fine at BSE-120)."
- **`input_latch` (@0x802A600C) is unavailable under BSE.** fpspatch notes that hook
  "belongs to the ALWAYS-ON substep-pin section" under BSE, and two C2s on one hook
  silently last-writer-wins — which is exactly why the select gate moved to
  `0x802A8054` in the first place.

So the fix wants either the chain-window threshold scaled by G at its compare site, or a
general BSE read()-entry gate at `0x802A8054` for gameplay (not just select), behind the
usual `==2.0f` guard. The second is broader and riskier: it would change every
trigger-edge consumer at once, and the select-gate comments warn that mis-phasing a pad
gate eats roughly half of all A-presses.

## Ruled out

- **Not a missing code.** `switch_rate.py --fps 120 --aspect 3` had been run; 19 codes
  enabled including both `fork kxe` force codes and all 11 BSE-120 baseline correctness
  fixes. Nothing relevant sits installed-but-disabled.
- **Not `input_latch` (#22).** Unreachable at G=2, and that bug drops edge presses
  stochastically — it would not scale smoothly with the rate.
- **Not EmulationSpeed.** 2.0 in both INIs, verified pre-boot; speed and audio tempo
  are both correct.

## Proposed catalog row

| # | Jump chain window | Double/triple jump hard at 60, impossible at 120 | Post-landing chain counter consumed at the render rate; threshold constant is 30Hz-tuned | scale threshold ×G at the compare, `==2.0f`-guarded (cf. #38) | untested | OPEN (BSE) |

## Note for the client setup docs

Two client-kit gaps found in the same session, both worth folding into
`SETUP-CLIENT-120.md`:

1. `iso_for()` maps 120fps → `BSMSO-GMSE01.iso`, but clients are only given
   `BSMSO-GMSE01-highfps.iso`. Every client hits `FileNotFoundError` on first launch.
2. Dolphin's user directory is not reliably `%APPDATA%\Dolphin Emulator` — a legacy
   `Documents\Dolphin Emulator` from another install wins, and every INI edit then lands
   in a file the emulator never reads (silent: no error, config simply ignored).
   Forcing portable mode with a `portable.txt` next to `Dolphin.exe` makes it
   deterministic. `switch_rate.py` hardcoded the `%APPDATA%` path.
