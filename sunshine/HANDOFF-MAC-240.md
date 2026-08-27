# HANDOFF-MAC-240: pushing the Mac past 120 — benchmark session 2026-08-24

Goal: highest stable rate on the MacBook, starting with a 240 attempt. Session ended
mid-work (Claude restart); state below is exactly resumable.

## Measured results (Delfino Plaza, user playing, stats = last 60–90s of
`~/Library/Application Support/Dolphin/Logs/{render,vblank}_times.txt`, method:
`LogRenderTimeToFile = True`, parse timestamps → mean/p99/worst-2s)

| run | config | mean VPS | worst 2s | game speed |
|---|---|---|---|---|
| baseline | single-core, 240 profile (EmulationSpeed 4.0) | **136.5** | 107 | 0.57x |
| no-peek diag | same + `EFBAccessEnable = False` | **~194–199** | (41s window) | 0.83x |
| peek gate | same, EFBAccess **True**, fpspatch `peek_gate` v1 | **~195 (187–206)** | — | 0.81x |
| **+ dual-core** | peek gate + `CPUThread = True`, windowed | **240 FLAT (throttle-capped)** | dips 233–235 by eye; one 151/190 bucket | **1.0x — 240 ACHIEVED** |

**2026-08-24 FINAL: the M2 MacBook holds 240 (4x) at correct speed** — peek gate +
dual-core, windowed. Five consecutive 30s buckets at a flat 240 in Delfino play.
User-confirmed by eye. NOT yet soak-tested: dual-core is the FIFO-desync/Metal-OOM
config (2026-08-22 Ricco segfault) — soak Ricco Harbor + level wipes before calling
it stable; the peek gate cuts cross-thread EFB syncs from 240+/s to ~30/s which
plausibly shrinks that desync surface, but that is hypothesis not verdict.

### SyncGPU + per-level results (same day, later)

The desync is REAL and immediate: unsynced dual-core panicked (`Unknown Opcode
0xcb`) the instant Bianco Hills was entered. A/B ladder (Delfino 60s windows,
user playing; battery confound on the SyncGPU rows — re-verify on full charge):

| config | Delfino | Gelato | Bianco | verdict |
|---|---|---|---|---|
| unsynced dual | 240 flat | 228 | FIFO panic ON ENTRY | fast, fragile |
| `SyncGPU = True` dual | ~150 | — | ~100, SURVIVES entry + play | stable, −90 VPS |
| single-core | ~195 | — | — | stable |

- SyncGPU's cost profile: CPU thread 56% idle in `Fifo::WaitForGpuThread` /
  `BlockingLoop::Wait` — the throttle, not compute.
- **Bianco ~100 VPS is the VIDEO thread's Metal draw-encode wall** (`DrawIndexed`/
  `PrepareRender` ~80% busy, CPU thread idle): pure draw volume, ~2x Delfino's.
  No threading config touches it. Cross-platform match with HANDOFF-PC item 13
  ("Bianco caps ~170"). Fix = reduce Bianco's draws (class B: cull/LOD project)
  or accept per-level rate targets (Bianco is full-speed at a 120 target).
- Unsynced pacing is jerky at cap (OSD 230–250 wobble). SyncGPU also kills that.
- **WINNER (tested same day): loose SyncGPU — `SyncGPU = True` +
  `SyncGpuMaxDistance = 1000000` / `SyncGpuMinDistance = -1000000`.** Delfino
  230–240 (full unsynced speed), ZERO FIFO errors, and **survived the Bianco
  entry acid test** that insta-panicked unsynced twice. Rationale: the M2's
  ARM weak memory ordering is why unsynced desyncs (GPU thread reads FIFO ring
  before CPU-thread writes are visible); SyncGPU's sync points are real
  barriers, and the loose distance just makes them cheap. Mirrored into
  `sunshine/dolphin-config/Dolphin.ini` (setup-kit default). A second unsynced
  crash mid-Gelato (opcode 0x14, ~20 min in, LR=SelectThread — generic race)
  had already demoted unsynced to benchmark-only.
- Per-level video-thread walls under the winner config (full speed at a 120
  target in all of them; the CPU thread idles — every wall is Metal encode):
  Delfino 240 / Gelato 228 / Bianco ~100 (DrawIndexed draw volume) / Pinna
  ~66 (`BeginRenderPass` churn = per-frame EFB screen-copies, the shimmer
  grab — 30Hz-gate the CAPTURE next, not just its BTK pace). User reports
  star-sparkle + rocket-launch cloud particle bursts visibly dip fps (JPA
  quad-per-particle draw spikes) — same class-B diet list.
- Video log channel is now armed (Logger.ini VIDEO=True, WriteToFile) for FIFO
  forensics; unknown-opcode grep on dolphin.log after any dual-core session.

2026-08-24 later session: `peek_gate(fps)` SHIPPED in fpspatch (default-on, stock
bundle, all rates; `--no-peekgate`): C2 whole-fn 30Hz gates on TMario::drawSyncCallback
0x8024D17C (the GXPeekARGB Mario-occluded flag — the ONLY GXPeekARGB caller in the dol)
and TSunMgr::drawSyncCallback 0x8002E270 (the 17x GXPeekZ flare sampler). Scratch
0x1700/0x1704. Matches the no-peek diagnostic = full win, visuals kept. Profile after:
PeekEFBColor GONE from hot leaves; remaining readback tier = ReadTexels/Flush (EFB
copies), plus Present/BindBackbuffer + draw submission.

**TRAP (cost run 3): `[Display] Fullscreen = True` on the built-in ProMotion panel
hard-caps presents at ~119.88/s regardless of `VSync = False` (macOS throttles
fullscreen Metal drawables to the 120Hz refresh). Benchmark WINDOWED, or fullscreen
only on a high-refresh external.** Flat 119 + tight variance = this cap, not load.

+45% from ONE config flip. `sample`-profile of the baseline (fpsprofile.sh) put
`FramebufferManager::PeekEFBColor` → `-[MTLCommandBuffer waitUntilCompleted]` as the
top emulation-thread stall (351 samples/5s), plus a second tier of EFB-copy
`ReadTexels`/`StagingTexture::Flush`. Classic PERF-PLAYBOOK class A.

## Diagnosis

The game calls `GXPeekARGB` (EFB color peek) every rendered frame — prime suspect is
the sun-glare/lens-flare visibility test — and at 4x rate each peek is a synchronous
Metal pipeline flush. NOTE the playbook's old caution: an earlier session NOP'd the
flare `GXPeekZ` at *Noki* and saw nothing — Noki's stall was EFB-copy readback, not
peeks. This time the profile *directly* fingers PeekEFBColor in Delfino, and the
`EFBAccessEnable=False` A/B measured the payoff (+58 VPS). Not a red herring.

## Next steps, in order (UPDATED after the 240 result)

0. **Ceiling probe**: with 240 throttle-capped, try 300 (5x) / 360 (6x) profiles to
   find the new Mac ceiling. **Ricco soak** for dual-core stability before trusting
   any of it. Then: PC retest with the gate (see SYNC-240 2026-08-24 entry) — the
   PC's 5.17x ceiling was measured WITH peeks; 360 there may now be in reach.
   Peek gate is UNCOMMITTED on `fpspatch-generalize` (entangled with the WIP diff).

## Original next steps (pre-result, kept for context)

1. **Build the peek 30Hz gate** (the proper fix; keeps the flare rendering
   correctly): find the game-side `GXPeekARGB` caller (decomp: sun/TSunModel glare
   check; fingerprint → USA address), C2-gate it to native 30Hz per
   `research/PERF-PLAYBOOK.md` "The 30Hz gate" (240 ⇒ mask `andi. r0,rX,7`; use
   `fpspatch.py _rate_gate`). Expect ~3/4 of the +58 VPS back with visuals intact.
   Wire it into fpspatch like `noki`/`shimmer` (branch `fpspatch-generalize` already
   has uncommitted generalization work — `git diff` before touching).
2. **Second-tier readbacks**: after the peek gate, re-profile; `ReadTexels`/Flush
   rows remain (EFB-copy-to-RAM consumer). Same playbook treatment if a caller shows.
3. **Dual-core A/B** (`CPUThread = True` in Dolphin.ini): untested this session.
   Single-core serializes draw/FIFO/present onto the emulation thread (all visible in
   the profile). Known risk: FIFO desync panics → Metal OOM (see memory
   `sunshine-offline120-freeze-open`, 2026-08-22) — watch the Video log channel, and
   note EFB *peeks* under dual-core force cross-thread syncs, so run this A/B *with*
   the peek fix (or peeks off) for a clean read.
4. If 240 still short after 1–3, target 180 (3x) as the stable Mac rate, or fall back
   to the interpolation route for the panel rate.

## Machine state left behind (IMPORTANT)

- **`EFBAccessEnable = False` is LIVE** in `Config/GFX.ini` — diagnostic only, the
  sun flare misrenders. **Revert to True** (or delete the line) before normal play
  and before benchmark run 3.
- `Config/GFX.ini` also now has `LogRenderTimeToFile = True`, `ShowFPS/ShowVPS/
  ShowSpeed = True` (fine to keep for the session; turn off when done).
- GMSE01.ini: the launcher applied the **Offline 240** profile (9 codes:
  `$SMS 240fps bundle` regenerated fresh, FOV 69, 16:10 set, camera/FLUDD/savebox
  QOL; `$Pause while jumping` off — profile has it off). `EmulationSpeed = 4.0`.
  To go back to normal 120: launch the **Offline 120** profile via `sms`.
- Dolphin was left RUNNING at 240/no-peek with the user in Delfino Plaza.
- Repo: branch `fpspatch-generalize`, pre-existing uncommitted launcher+fpspatch
  changes (NOT from this session; this session wrote only this file). Working-tree
  diff is the generalization work in progress.

## Measurement recipe (reuse)

Quit Dolphin → edit configs → `smslaunch` programmatic apply+launch
(`profiles.Store().get("Offline 240")` → `launcher.apply(p)` → `launcher.launch(p)`)
→ play ≥2 min in a fixed spot → parse `Logs/{render,vblank}_times.txt` (timestamps in
ms; diff consecutive, window last 90s). `fpsprofile.sh 5` any time it's slow.
