# HANDOFF — bug-free BSMSO 60fps (continue this work)

**For the next agent.** This session built a correct-speed **60fps** BSMSO online
kit (BSE FPS_60) so Kris's brother **Aaron** and **John** can play a bug-free 60.
Two threads are still open (landing-stun bake-in, 3-player perf). **Drive the
remaining work with SUBAGENTS** — spawn `heavy` for the cadence/RE + code changes,
`Explore`/`researcher` for audits, and verify everything both statically
(`fpspatch --check`, byte-diff 120/240) and in-game. Do not hand-derive risky
Gecko divisors solo; this session got burned twice on cadence class (see Lessons).

## NON-NEGOTIABLE constraints (Kris, explicit)
- **`HiresTextures = True` STAYS ON.** Do NOT turn HD textures off for perf.
- **`InternalResolution = 3` STAYS.** Do NOT lower internal resolution for perf.
- Perf must come from **puppet-rendering / engine** work, never a visual downgrade.

## SESSION 2 UPDATE (2026-08-28, later) — Kris switched HIMSELF back to 120
- **Kris is now on 120fps** (his own machine). He judged 60 "a good improvement, ready to
  ship to Aaron" and wanted his own game back at the snappier 120. Live-confirmed:
  framerate global `0x804167B8` = `40000000` (2.0), in-stage. This does NOT desync online:
  BSE sim is 120Hz constant at every render rate, so render rate is purely local.
- **How the 120 switch was done (repeatable):** Dolphin closed → `switch_rate.py --fps 120
  --aspect 2` (installs the 120 companion bundle; the 60 codes self-disable at 120 because
  they guard on the 60 framerate literal, so this swap is MANDATORY or you get 120 with no
  BSE fixes) → `play120.sh --online` (display 16:10, boot, `set_bse_fps --fps 120 --aspect 2`,
  server left up, fresh bridge). Server (dotnet `SMSO.ServerHost.dll`) was NEVER touched.
- **Lobby-invisibility bug FOUND + FIXED:** Kris's friends saw each other but not him. Cause
  was a **dead bridge** — the old `bridge.py` process was still alive but its TCP socket to
  `27015` was in state CLOSED (roster join lost). Fix = restart the bridge (play120.sh does
  it). Diagnose with `lsof -iTCP:27015` — a CLOSED python socket = invisible; look for an
  ESTABLISHED `localhost->27015` and a `[bridge] Joined as slot N` line in `/tmp/bridge.log`.
  Now: slot0 Aaron, slot1 Kris, slot2 J_Elbows (John), all three ESTABLISHED.
- **Landing verdict (the poke):** Kris said "it's better but still longer than default — maybe
  I'm just used to the sped-up 120 timings, idk." So the 0.5 poke HELPED but he couldn't
  cleanly separate residual-stun from 120-muscle-memory. The 0.5 scaling is mathematically the
  exact 120 wall-clock (8 ticks/60Hz = 16 ticks/120Hz = 133ms), so it's the right target for the
  60 kit; bake it (Task 1). If a residual persists after bake+re-test, chase `setUpperDamageRun`.
- **NEW BUG (Task 4): boats "hauling it" — CLIENT-LOCAL, John only.** Clarified in session 2:
  fast boats = the **little canal/plaza boats** (TFruitsBoat), and they are fast **only on John's
  client, NOT Kris's**. Boats are game objects (not networked puppets), so fast-only-on-John points
  at **John's local render/sim config**, not a shared code bug — likely John's machine runs a
  rate/EmulationSpeed the plaza boats aren't gated for. Catalog #32 already ruled TFruitsBoat
  "normal" at Kris's config. So this is NOT a fpspatch bundle fix — it's diagnose-John's-client
  (what fps/bundle is John actually running?). Deprioritized.

## Original live state (from session 1 — now superseded by the 120 switch above)
- Game was running at **true 60fps** (framerate global `0x804167B8` = 1.0, EmulationSpeed=1,
  HUD Speed 100%). The BSE-60 companion is confirmed working in-game.
- **Server up** (SMSO.ServerHost, `*:27015`) and **must stay up** — Kris said restart
  game not server. Bridge running, reattach it after any game
  relaunch (it follows the Dolphin pid). Roster: slot0 **Aaron**, slot2 **J_Elbows** (John).
- Kris's Tailscale IP `100.117.221.19` (server reachable for John).
- The landing-poke test above (`0x803DD254=8, 0x803DD268=2, 0x803DD27C=12`, were 16/4/24) was
  the session-1 live test; Kris's verdict is recorded in the SESSION 2 UPDATE.

## Git state
- Branch `fpspatch-generalize` (pushed to origin). NOT merged to `main` — the WINDOWS
  docs tell PC users to pull `main`, so Aaron needs either a merge (blocked earlier by the
  no-direct-push-to-main policy — open a PR: https://github.com/2-X/high-fps-sunshine/compare/main...fpspatch-generalize)
  or to pull the branch.
- **Uncommitted, needs committing** once the landing fix is confirmed:
  - `sunshine/research/scripts/fpspatch.py` — the jump-chain fps-agnostic fix (new
    `bse_status_fps` helper) + (pending) the landing/getup scaling.
  - `sunshine/research/codes/bse60-companion-v1.txt` — regenerated bundle.
  - (`set_bse_fps.py` is a pre-existing unrelated edit — leave it.)

## DONE this session (don't redo)
1. **Generalized `fpspatch.py --bse` to emit FPS_60** (branch commit b66582e). `bse_supported`
   admits G≥1; `bse_sim_fps` now constant 120 (the true BSE sim rate at every rate);
   render-class N=2, anmrate ×0.5; **parity/boid/game-clock/substep-pin deliberately
   OMITTED at 60**. 120/240 output byte-identical (regression-diffed). `--check` OK at 60/120/240.
2. **Parity + boid omissions CONFIRMED correct by in-game eye-test** — particles look
   right at 60 (Kris: "all the fixes work except the landing fix"). So the CALC_ANIM =
   native-60Hz reasoning held for those.
3. **Jump-chain window fix made fps-agnostic** (subagent): the status machine is
   RENDER-paced, so the divisor is `bse_status_fps(fps)//30 = min(fps,120)//30` (×2 at 60,
   ×4 at 120/240), NOT the sim-paced constant 4. Chain records now 32 at 60 (verified in
   live RAM). This is the part that IS applied. See `bse_jump_chain`, `bse_status_fps`,
   and the `_check_bse` jump-chain assertion in fpspatch.py.
4. `switch_rate.py` made cross-platform (Mac): `dolphin_running` (pgrep), INI paths,
   force-step skipped on macOS (set_bse_fps does it live). Windows path byte-unchanged.
   Committed in 24382fe.
5. `sunshine/bsmso/WINDOWS-60.md` handoff for Aaron's PC (one command: `play240.ps1 -Fps 60`).
6. Perf: killed the 153MB hot-path **log flood** (`Logger.ini WriteToFile=False`) — that was
   the "lags when FLUDD comes out"; async shaders on (`ShaderCompilationMode=3`).
7. Diagnosed the "Shadow Mario laughing, not running" = a **remote puppet** (puppets render
   as `TEMario`), frozen by the known puppet-locomotion bug (catalog #35), NOT a game NPC,
   NOT a 60fps bug. Aaron/John data flows fine; the game-side puppet actor doesn't track it.

## OPEN TASK 1 — landing/getup stun at 60 (bake in the confirmed fix)
**Symptom:** landing a jump at 60 has an "extra delay stun." The chain records (32) are
correct; the stun is the **landing/getup records left stock by jump-chain v2**:
`+0x74=16 @0x803DD254`, `+0x88=4 @0x803DD268`, `+0x9C=24 @0x803DD27C`. These are ticked by
the same RENDER-paced status machine, so at 60Hz they recover ~2× slower than at 120Hz
(267ms vs the pleasant 133ms) → reads as a stun. The live poke halves them (→8/2/12) to
restore the 120 feel.

**If Kris confirms the poke fixed it** → spawn a `heavy` subagent to bake it in permanently:
- Extend `bse_jump_chain` (fpspatch.py ~line 2134) to ALSO emit the three landing/getup
  records scaled by `min(fps,120)/120` (a factor that is 0.5 at 60, 1.0 at 120/240 → only
  changes 60). Records: `0x803DD254`(16→8), `0x803DD268`(4→2), `0x803DD27C`(12). Same guarded
  `20`-if-equal-on-framerate-global data-write form as the chain records.
- Update the `_check_bse` jump-chain validator to expect them.
- HARD CONSTRAINTS: `fpspatch 120 --bse` and `240 --bse` output MUST stay byte-identical
  (diff before/after); `--check` OK at 60/120/240; regenerate `bse60-companion-v1.txt`.
- Then re-apply to the live game (`switch_rate.py --fps 60 --aspect 2` with Dolphin closed,
  relaunch, `set_bse_fps.py --fps 60 --aspect 2`, reattach bridge) and have Kris re-verify.

If the poke did NOT fix it, the stun is something else — investigate `TMario::setUpperDamageRun`
(0x80124238, in `research/animrate-audit.md`) or the landing animation path; don't force the
record change.

## OPEN TASK 2 — perf: ~30fps with 3 players on screen
Drops from 60 to ~30 with 3 puppets visible. **Within the non-negotiables above** (HD +
IR=3 stay). Spawn a `researcher`/`heavy` subagent to find the puppet-render cost and cut it
without touching textures/resolution. Leads:
- Puppets are full `TEMario` models × FLUDD. **Puppet FLUDD water is cosmetic-only** (see
  memory `sunshine-bsmso-puppet-fludd-cosmetic`) — a candidate to skip for remote puppets.
- Puppet model LOD / distance culling; are 3 full-detail models drawn every frame?
- The EFB peek gate is already on (good). Profile the Metal draw/encode cost of the extra
  models (SYNC-240 / HANDOFF-MAC-240 methodology).
- Server-host CPU contention: SMSO.ServerHost busy-waits a core (WINDOWS-120 note) — renice
  it and the bridge below Dolphin so they don't steal from emulation.
- Measure FIRST (the project's PERF-PLAYBOOK "MEASURE FIRST" rule); don't ship blind gates.

## OPEN TASK 4 — boats "hauling it" at 60 (NEW, session 2)
**Symptom:** Kris reports boats moving too fast (observed while on 60). Untriaged — no address,
no cadence class yet. **Drive with a `researcher`/`heavy` subagent** (do NOT hand-derive the
divisor solo — cadence-class trap, see Lessons).
- Prior art: catalog #32 `TFruitsBoat` (one mode stock, other mode 4x SLOW at 240) + `TBoidLeader`
  (4x fast) were WONTFIX "false alarm" for PLAZA gondolas — Kris called those "normal" earlier.
  This report may be a DIFFERENT boat/mover (Ricco ride-boats, a level platform-boat) OR the same
  actor newly-obtrusive at 60. Start from `Enemy/fruitsboat.cpp` (in `research/animrate-audit.md`)
  and the moving-platform / `TMapObjBase` mover path.
- Classify the cadence FIRST: sim (120Hz constant → correct at every rate, would NOT be the cause),
  render (`min(fps,120)`), or substep. "Too fast at 60" points at a per-tick delta applied on a
  clock faster than the boat's intended 60Hz (substep/sim), NOT render. Prove with a live RAM read
  of the boat's position/velocity delta per frame at 60 vs the intended speed.
- Repro needs a **60 session** (Kris is on 120 now). Either bounce Kris to 60 for a test, or drive
  the ghost bot at 60. The subagent should produce diagnosis + a candidate gate; live-verify before
  shipping (PERF/"MEASURE FIRST" discipline, no blind gate).

## OPEN TASK 3 — housekeeping
- Commit the uncommitted fpspatch.py + bundle once Task 1 lands.
- Get the branch onto `main` for Aaron (PR link above; direct push is policy-blocked).
- Update `HIGH-FPS-CATALOG.md` (the 2026-08-28 BSE-60 note) with the landing/getup finding.

## LESSONS (why "use subagents" + verify)
- **Cadence class is the trap.** `bse_sim_fps` was changed to constant 120 (correct for
  SUBSTEP-paced: blue-coin/shimmer) but that silently broke the jump-chain, which is
  RENDER-paced (`min(fps,120)`) — latent because they coincide at 120, diverge at 60. The
  landing/getup records are the same render-paced class. Whenever a divisor "happened to
  work at 120," re-derive it for 60 from the actual cadence, and prove it with a live read
  or eye-test, not assertion.
- **Verify omissions too.** The parity/boid omissions were eye-test-confirmed; don't assume.
- **Static + live.** `--check` and byte-diffing 120/240 catches regressions; only in-game
  confirms feel. Kris is the eye-test; keep him in the loop per change.
