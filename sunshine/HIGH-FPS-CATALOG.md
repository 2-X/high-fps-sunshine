# Super Mario Sunshine High-FPS Catalog

A single living reference for **every** high-FPS bug / effect / consideration in the
Super Mario Sunshine (GMSE01 / USA) high-framerate project, across both engines:

- **STOCK sim-rate approach**: Dolphin runs the console faster than real time
  (`EmulationSpeed = G`) while a Gecko bundle (`fpspatch.py`) renders every VI field
  and subdivides the sim delta. This is the everyday 120fps kit.
- **BSE / BSMSO-online approach**: the *Better Sunshine Engine* Kuribo mod drives its
  OWN frame clock. Almost none of the stock Gecko frame-hacks work under it; you poke
  BSE's native settings instead. This is the online-multiplayer kit.

---

## How to use / how to update this doc

- **§1**: architecture and load-bearing gotchas (read this first).
- **§2**: the master table: one row per bug/effect. Scan the **Current state** column.
- **§3**: per-item detail sections (addresses, actual Gecko, reasoning, traps).

**To add a new high-FPS bug:**
1. Append a row to the **§2 table** with a stable Name.
2. Add a matching `### Name` subsection under **§3** with: symptom, root cause,
   address(es), the Gecko code (or generator function), reasoning, gotchas.
3. Keep the **Current state** column current (`FIXED` / `PENDING` / `NEEDS-TEST` /
   `WONTFIX`) and note the date + engine (stock / BSE) it was confirmed on.
4. If it is a `fpspatch.py` fix, cross-reference the generator function name so it stays
   in sync with `sunshine/research/scripts/fpspatch.py`.

**Sources this was mined from (2026-08-12):** `~/.claude/.../memory/sunshine-*.md`
(~25 files), `sunshine/research/memory/*.md`, `sunshine/research/scripts/fpspatch.py`,
`sunshine/research/codes/*`, `sunshine/bsmso/PROTOCOL.md`, `sunshine/bsmso/mac-online/bridge.py`,
and prior session transcripts.

---

## §1 Architecture & key facts

### 1.1 The stock sim-rate mechanism
Set **G = FPS / 60**. The bundle rescales FOUR+ independent things (see
`fpspatch.py` docstring, the single source of truth):
1. **Framerate global `0x804167B8`** ← `float(G)` (write `044167B8 <word>`), plus
   `EmulationSpeed = G`. `60=1x, 120=2x, 180=3x, 240=4x, 360=6x`. Many hooks READ this
   word and self-scale (and self-disable at the stock `0.5f`).
2. **Substep granularity**: stock accumulator constants `600` / `5`
   (@`0x8029985C`/`74`/`80`) scaled by G; this pins the SIM at **120 Hz at every G**.
3. **Emitter / particle gate**: but see the trap below (it is the CONSTANT 2, not G).
4. **Noki pollution / SE / wipe / audio-pump gates**: these are native **30 Hz** work,
   so their divisor is **FPS/30 = 2G**, NOT G.

**SDA addressing (get it right or codes silently misbehave):** `r2 = 0x80416BA0`
(from `__init_registers` @`0x8000536C`). So the framerate global is `-0x3E8(r2)`.
`-0x3C8(r2)` = `0x804167D8` = a plain `60.0f`. An old anmrate bug used `-0x3C8` and
divided by 120 instead of 2G. `--check` now asserts this.

**The "1-in-2 particle" trap (three doc reversals):** `CUE_CALC_ANIM` fires on the LAST
substep of each rendered frame, **~120 Hz at every G**, NOT render rate. So the JPA
parity divisor is the **CONSTANT 2** (`120/2 = 60 Hz` native JPA rate), same class as the
Poink `40` and the cogwheel `4`. A "generalize to 1-in-G" edit ran JPA at `120/G` Hz
(fine at 120, 2x-slow at 240). Do not re-flip without new evidence.

### 1.2 The Mac hardware ceiling (Route B)
This Mac (Apple Silicon M2 Max) sustains only ~2x emulation for Sunshine, so **120fps is
the working ceiling**. Requested 3x delivered ~1.5x, 6x delivered ~180fps, CPU/emulation
bound, not GPU (same at native IR). So 180/240/360 sim-rate tests are **confounded by the
ceiling** (Mario always looks ~2x fast). Correct-speed >120 requires **Route B: frame
interpolation** in the Dolphin present path (keep sim at 60/120, interpolate transforms
between ticks). A v1 interpolator is IMPLEMENTED + builds (env `DOLPHIN_FRAME_INTERP=N`,
Present.cpp ViSwap gap-fill blend) but runtime-unverified; user prefers the sim-rate feel
(no added latency) and rejected blend v1's ghosting.

### 1.3 The BSE-owns-subsystems insight (critical for online)
BSMSO ships the **Better Sunshine Engine** via a Kuribo mod. BSE runs its OWN frame clock:
`BetterSMS::getFrameRate() = 30 << mFPSValue`, and BSE's `updateFPS()` **re-writes the
stock frame global `0x804167B8` EVERY frame** from `mFPSValue`. Therefore:
- **The stock fpspatch Gecko bundle does nothing under BSE**: any write to
  `0x804167B8` is instantly clobbered (that was the 4x/2x garbage speed).
- **The fix is to poke BSE's native setting ints** (0x28-byte Setting objects clustered
  ~`0x8051Exxx`, module base `0x804bcce0`), which BSE does NOT clobber:
  - **FPS: `mFPSValue @0x8051E528`** ← `2` = FPS_120 (`0=30, 1=60, 2=120`). **No FPS_240
    case exists** → 240 online needs a BSE *source* mod. The bridge writes this every loop.
  - **Widescreen: `gAspectRatioSetting @0x8051E4D8`** ← `3` = WIDE 16:9 (`2=16:10, 4=21:9,
    5=32:9`); pair with Dolphin `wideScreenHack=False` (disable stock `$Widescreen`, it
    fights BSE).
  - **FOV: `gViewportSetting @0x8051E500`** (`0=SMS, 1=SM64×0.9, 2=SMG×0.8`): COARSE only,
    BSE has no exact-FOV knob. `2` caused scene-vs-shimmer FOV mismatch; keep at SMS.
- There is also a Gecko `$BSE Force 120 FPS [kris]` that works IF the title matches exactly.

### 1.4 Load-bearing gotchas (the setup that must be right)
- **MEM1 must be 64 MB** (`RAMOverrideEnable=True`, `MEM1Size=0x04000000`, applies at BOOT).
  BSMSO's `SMSO_RemotePuppets` heap is in an expanded MEM1 arena; 32 MB → puppet silently
  skipped, 40 MB → arena overruns → `Unknown Pointer 0x828f2320` crash. Use 64 MB.
  (Stock kit only needs the `0x02000000` override for the code-cap relocation.)
- **`EnableCheats = True`**: global AND per-game. It silently reverted to False once and
  no Gecko ran at all.
- **Per-game `EmulationSpeed` overrides the global**: a per-game `1.0` beats a global `2.0`.
  Set per-game `EmulationSpeed = G`.
- **Gecko code-cap relocation** (`high-fps-dolphin.patch`, `GeckoCode.cpp` + `MMU.cpp`)
  lifts the silent ~406-code-line cap to 32766 by relocating the list to
  `0x81800000..0x81840000`. Before it, everything past ~406 lines was **silently dropped**
  (tail of bundle + all of Widescreen + all of FOV never ran). After installing it,
  RE-TEST late-list codes. The relocated list sits **64 KB below BSMSO's arena**, so it
  coexists with online, but it is why online was gated on this patch too.
- **Exact-title match or codes silently drop.** A `[kris]` suffix or an enabled-list title
  that drifts from the code title disables the code with NO error. Verify after every
  Dolphin INI mutation (Dolphin rewrites the user GameSettings INI on quit).
- **Codesign `get-task-allow` after every Dolphin rebuild**: re-sign the .app BUNDLE with
  `DolphinEmuDebug.entitlements` (a get-task-allow-only plist strips allow-jit and dyld
  rejects Homebrew Qt). Needed for live memory tools + the Mac online bridge (no sudo).
- **Audio needs the custom Dolphin build**: the tempo fix is a binary patch
  (`SystemTimers.cpp` `GetAudioDMACallbackPeriod` ×EmulationSpeed), NOT a setting. Stock
  Dolphin plays sped-up. Config dir is shared, so only the binary distinguishes builds.
- **C2 cave is small and overflows SILENTLY.** ~30 blocks / ~1.2 KB. If blocks stop taking
  effect, drop optional ones (`--no-stars`, `--no-poink`, `--no-bluecoin`) before
  suspecting the code. Also: Dolphin's C2 handler **overwrites the last word** of each
  block with its branch-back → every block must end in a `00000000` pad, and every path
  must converge on that exact last word (pad interiors with `nop`, never a 2nd zero).

---

## §2 Master table

Legend for **BSE status**: "BSE handles" = FPS_120 corrects it natively; "stock fix works"
= the stock Gecko targets a BSE-untouched vanilla address and still applies; "BROKEN" =
disabling the stock bundle removed the fix and BSE does not cover it.

| # | Name | Symptom at high-FPS | Root cause | Stock fix (addr / mechanism) | BSE / BSMSO status | State |
|---|---|---|---|---|---|---|
| 1 | M-portal glow | Rainbow-M stage portals stay dark / unenterable | Glow = rise(30Hz realtime) vs decay(per-frame); at 120 decay cancels rise. Master switch: `0x70&1` gate | `PROXIMITY_GLOW` reimpl (XZ dist) + `FORCEOPEN` (calls real `startOpen`) | Untested online (single-player feature) | FIXED (stock) |
| 2 | Camera look-up | Can barely look up (~5° floor) | `mXAngleMin` floor; ratio drives zoom too | `$Camera look-up vN` C2 @`0x8002510C`/`0x80024D1C`, scratch `0x800016F0` (v10/v11) | N/A online | FIXED (stock, v10/11) |
| 3 | FOV | Default ~50° FOV | User preference, not a bug | `$FOV 60` TWO hooks: C2 @`0x8034A404` + C2 @`0x802260CC` | BSE `gViewportSetting` (coarse); stock disabled | FIXED (stock); DISABLED under BSE |
| 4 | Widescreen | 4:3 pillarbox | Native 4:3 | `$Widescreen [gamemasterplc]` + `wideScreenHack` | BSE `gAspect=3` + Dolphin `wideScreenHack=False` (stock disabled; it fights BSE) | FIXED both |
| 5 | Audio tempo + pitch | Sped-up / high-pitched audio | DMA period vs EmuSpeed; mixer resamples | Dolphin binary patch (tempo) + `AudioPreservePitch=True` (pitch) + buffer 136 | Same (build-level, engine-agnostic) | FIXED |
| 6 | BGM DSP coin-toss | Level BGM silent (per-load coin toss) | DSP voice-limiter misfires under 2x-slow DMA | `0440CDB4 00000000` (`DSP_LIMIT_RATIO=0`) + tempo guard `C231B8C8` | Stock fix targets vanilla addr, should still work | FIXED (stock) |
| 7 | Particle / flash parity | Emitters frozen / flash-invisible on level reconstitute | `SMSGetAnmFrameRate=0.5 → fctiwz=0 → 0 calcs` | 3× parity C2 @`0x802887A8`/`0x80288D30`/`0x80288DEC` (CONSTANT 1-in-2) | BROKEN under bare BSE-120 → re-added as guarded C2 at same addrs | FIXED both |
| 8 | JPA 2x-slow at 240 | M-portal atoms decompose/recompose at half speed | 1-in-G particle gate ran JPA at 120/G | Same 3 parity blocks, divisor pinned to CONSTANT 2 | see #7 | FIXED (stock) |
| 9 | Blue coin timer | Spray-spawned blue coins vanish too fast | Lifetime is a FRAME counter (`mStateTimer`), not stopwatch | `$Blue coin timer v6` C2 @`0x801BE880`, ¾-rate (keep 1-of-4) | `v6-BSE` installed + ENABLED 2026-08-13: keep **1-of-4** (BSE ticks perform at raw 120Hz, vs the stock kit's measured ~40/s → ¾-rate). One-word invert of v6's %4 branch (`fpspatch bse_bluecoin()`) | FIXED (stock 120); NEEDS-TEST (BSE, ~20s target) |
| 10 | Race / countdown clocks | Clocks run 2x fast at 120 | Clocks read `OSCheckStopwatch` (timebase), 4 callers | `$Game clock fix v15` C2 @`0x80348180`, divide 64-bit ticks by G | self-gated ==2.0f, emitted in `fpspatch --bse`, installed 2026-08-13 | FIXED (stock); NEEDS-TEST (BSE) |
| 11 | Petey vomit window | Barf/mouth-open window ~4x too short | `changeBck` writes RAW `mSLVomitAnmRate` to frameCtrl+0xC | `$Petey v16` C2 @`0x800955CC` (×0.25); superseded by `anmrate()` | covered by the BSE anmrate code (installed 2026-08-13); do NOT also enable v16 | FIXED (stock); NEEDS-TEST (BSE via anmrate) |
| 12 | Poink premature explosion | Poink pig explodes mid-flight (never reaches Petey) | Explosion nerve pushed externally at flyTimer ~9 vs ~36 | `$Poink v14` C2 @`0x800e5e44` (flyTimer<40 → revert Fly nerve) | bug confirmed live under BSE; guarded v14 installed via `fpspatch --bse` 2026-08-13 | FIXED (stock); NEEDS-TEST (BSE) |
| 13 | Noki pollution perf + the Bianco intro freeze | Ep.1 caps ~105fps on Mac; gate froze Bianco Ep.1 intro (5x, deterministic pollution-frame 521, BOTH engines) | Readbacks FPS/30 x too often (Mac/Metal); freeze = J3D push-front inserts have NO already-head check — double entry under the gate's skipped clear/rebuild writes `packet->next = packet`, draw walks the 1-cycle forever | `noki_gate` v6 (gates + `NOKI_QRESET` + dedupe + copy gate) **+ REQUIRED `$J3D duplicate-entry guard v2`** (4 C2s @`0x802EDC18`/`0x802ED914`/`0x802EFA80`/`0x802EFAA0`: chain-walk on the shape-list inserts + head-check on the bucket inserts — v1's head-check alone missed weave cycles, freeze #6 was a 3-cycle; `research/codes/j3d-dup-entry-guard-v2.txt`) | The 2026-08-19 marathon (full story: HANDOFF-NOKI-PERF §v4→§RESOLVED): 3 upstream fixes failed identically; freeze #4 (OFFLINE — engine independence proven, BSE exonerated) found the self-loop at the SHAPE-packet level. Guard fixed it at the corruption site; **offline Bianco intro confirmed surviving with the gate active**. Guard is always-on hardening in both launchers + kit INIs (deployment gotcha: launchers rewrite [Gecko_Enabled] — verify hooks in MEMORY). ⚠ PC/Vulkan: gate gives no measured fps win (Video-thread-bound, see SYNC-240 profiling) — kept for Mac/Metal (39%) + parity | FIXED offline (in-game); BSE v6 NEEDS-TEST |
| 14 | HUD perpetual stars | Star sparkles never stop after unpause | Leaked JPA emitters (pause-menu + banner) on unpause | `$StarFix v4` (pauseOut @`0x8014A850` + bounce @`0x80155D8C` + watchdog @`0x80324EB8`) | guarded v4 installed via `fpspatch 120 --bse` 2026-08-12 | FIXED (stock); NEEDS-TEST (BSE) |
| 15 | Repeating-SE 30Hz | Hover/creak/tentacle SEs FPS/30 x too fast | JAudio SE process pair runs per rendered frame | `se_frame_gate` C2 @`0x80305204`/`0x80305958` (blr, 1-in-FPS/30) | guarded gate installed via `fpspatch 120 --bse` 2026-08-12 | FIXED (stock); NEEDS-TEST (ear, both engines) |
| 16 | SaveBox Continue-on-top | (QoL) "Save and Continue" is default | Label + case order | `$SaveBox Continue on top` 4×04 + C2 @`0x8015CAC0` | vanilla addr, works | FIXED (stock) |
| 17 | Tank controls | (QoL) tank-style steering | User preference | `$Tank Controls v8` (checkController region) | vanilla addr | FIXED (stock, opt-in) |
| 18 | FLUDD aim invert | (QoL) up-aims-up spray + first-person + Mecha Bowser fight | User preference | `$FLUDD Aim Invert v3` = v2 + `040310DC FFA00090` (fight-only coaster-cam vertical negate in `ctrlJetCoasterCamera_`) | vanilla addrs | FIXED (v2 confirmed); Mecha Bowser word NEEDS-TEST |
| 19 | Animal movement rate | Birds fly/walk at 1/4 speed (+ 4x-long phases) | Substep-paced speeds × stub 0.5; duration helper 4x | `animal_speed()` + `animal_duration()` (×4 restore) | slow-birds bug confirmed live under BSE; guarded blocks installed via `fpspatch --bse` 2026-08-13 (duration hook needed an r0-safe guard) | FIXED (stock); NEEDS-TEST (BSE) |
| 20 | Skid U-turn | Running U-turn nearly impossible | 120Hz pad sampling lets yaw track through the stick flip | `turnaround_fix()` C2 @`0x8025AF64` (4-tick stale face) | ships with substep | FIXED (stock, playtest-pending) |
| 21 | Shine-select cadence | Cursor repeat ~3x fast; menu shines flicker | TSelectDir runs at render rate | `select_gate` @`0x802F7DBC` + `select_grad_gate` @`0x80175584` (1-in-ceil(G/2)) | render-rate; G=2 no gate | FIXED (stock, G>=3) |
| 22 | Input latch / dropped inputs | ~1-in-3 edge presses lost at G>=3 | Pad read once per DISPLAYED frame → repeated per substep | `input_latch` C2 @`0x802A600C` (zero trigger/release on skip frames) | needs substep; unreachable at G=2 | FIXED (stock, G>=3) |
| 23 | Wipe pacing / decompose-recompose | Level-entry decompose/recompose 2G x too fast | Hx wipes are frame-counted for 30fps | `wipe_pace` (1-in-FPS/30) + Test5 handling (`wipe5_swap` to Hx_Test4 at G>=3) | guarded `wipe_pace` installed via `fpspatch 120 --bse` 2026-08-12. Hypothesis: the "missing" decompose/recompose was the un-gated wipe playing 4x fast (~0.17s), not absent | FIXED (stock); NEEDS-TEST (BSE) |
| 24 | Audio pump / 240fps silence | Total music silence + SE flicker at 240 | MSound::mainLoop SE processing at render rate thrashes 64-voice pool | `audio_pump_gate` C2 @`0x80014DA8` (1-in-FPS/30) | render-rate class | FIXED (stock, G>=3) |
| 25 | THP movie pace | Silent M-portal preview movies play G x fast | THPPlayer paces off VI retraces | `thp_pace` (divisor 5994*G; audio movies excluded) | render-rate class | FIXED (stock) |
| 26 | Ricco hook slide-clank | "womp womp" clank near gondola hooks at 240 | `TRiccoHook::perform` requests SE every tick, timer never re-arms | `riccohook_se_gate` (1-in-FPS/30, on pump counter) | render-rate class | FIXED (stock) |
| 27 | anmrate raw setters | ~15 boss/enemy anims play 4x fast | Raw `stfs` of param rate to frameCtrl bypassing the getter | `anmrate()`: raw-rate hooks ×`R/(2G)`, self-disabling (supersedes v16) | Petey/Gooper too-fast confirmed live under BSE; self-gated blocks emitted in `fpspatch --bse`, installed 2026-08-13 | FIXED stock (Petey confirmed); NEEDS-TEST (BSE + remaining sites) |
| 28 | Shimmer / heat-haze | Mirage pulsates 4x fast | `TShimmer` BTK advanced per CUE_MOVE at fixed 1.0, never scaled | `SHIMMER` generator in fpspatch (default-on, `--no-shimmer`); C2 @`0x8019F89C`, self-gates on `!=0.5f` | active under BSE 2.0f, installed 2026-08-12 | NEEDS-TEST (stock + BSE) |
| 29 | Talk-init debounce | Talk-to-NPC impossible at 360, ~50% at 180 | movement_game/changeState cadence diverge under substep | `TALK_INIT_FIX` `0429A908 540007FF` (test bit0 not bit1) | ships with substep | FIXED (stock) |
| 30 | Low-arena scratch collision | Sand-castle secret-entry soft-lock at 240 | Camera 0x40-byte block @`0x800016F0` stomped wipe/pump counters | Slot map moved: Noki `16E0/16E4`, SE `16E8`, camera `16F0`, wipe `16F4`, pump `16F8`, turnaround `1720`, camera-code `1730+` | scratch discipline | FIXED (stock) |
| 31 | BSMSO idle→settings crash | ISI exception entering controller settings online | Ghost bot's unbounded AnimId ramp indexes past `gMarioAnimeData[411]` in `TMario::setAnimation` | N/A | clamp anim_id `%16` in ghost_bot.py + sanitize `<=410` in bridge.py | FIXED (BSE) |
| 32 | Fruits-boat / boids | (suspected fast plaza boats) | TFruitsBoat one mode stock, other 4x SLOW; TBoidLeader 4x fast | none, user confirmed "normal", no complaint | n/a | WONTFIX (false alarm) |
| 33 | Sun lens-flare probe | (perf) 17 GXPeekZ readbacks/frame | occlusion sampler N x too often | `SUN_PROBE` `0402E28C 60000000` | opt-in only (recovers no measurable time, breaks flare) | WONTFIX-by-default |
| 34 | Widescreen wipe fix | wipe copy-vs-draw misalignment in 16:9 | separate from wipe5 morph | `$Widescreen wipe fix v2` | user "not fully working" | PENDING |
| 35 | Ghost puppet locomotion | Online puppet "floats", no locomotion anims; departed puppets freeze forever | bridge doesn't drive locomotion AnimId; no despawn on leave | N/A | despawn-on-leave IMPLEMENTED 2026-08-12 (roster-diff → snapshot zero + RosterHud Kind=2); ghost locomotion scaffolding (true velocity + 30fps anim_frame + idle). walk/run AnimIds need live capture | PARTIAL (BSE) - live test + anim-id capture |
| 36 | PC 240fps online | 240 online unsupported | BSE has no FPS_240 case (`mFPSValue=3` hits uninitialized paths) | N/A | BSE fork with FPS_240/280/320 BUILT 2026-08-12 (`bsmso/BetterSunshineEngine-highfps-v400.kxe`, in `BSMSO-GMSE01-highfps.iso`); ⚠ new kxe shifts `mFPSValue` off `0x8051E528`: bridge poke + `$BSE Force 120` addr are old-kxe-only | IN-PROGRESS (fork built, boot-test pending) |
| 37 | Pachinko FLUDD "suction" | Top-left red coin nearly unreachable at 120; hover pulls Mario toward the middle (Delfino pachinko secret) | UNSOLVED. CUE_MOVE is 120Hz-pinned at every rate, so the naive rate theory fails; suspects: per-render splash/particle pushes, input-poll-rate, spawn-count effects | none; see `HANDOFF-PACHINKO-BUG.md` (diagnosis only, never reproduced under instrumentation) | untested | PENDING (diagnosis only) |
| 38 | Menu key-repeat 4x (BSE) | Holding up/down in save-select / in-level pause races through options; Delfino pause immune (2-item menu = idempotent repeats) | Repeat delay/interval (`20/6 ÷ SMSGetAnmFrameRate` = 10/3 TICKS, correct) counted by `read()` which BSE runs ungated at 120Hz (stock kit was immune via input_latch) | N/A at stock | `$Menu key-repeat BSE-120 fix v1` C2 @`0x802A89C8` (`slwi ×4` on r5/r6 pre-`setButtonRepeat`, ==2.0f guard), installed 2026-08-13 | NEEDS-TEST (BSE) |
| 39 | Shadow Mario chase off-path / wall-jam | Pinna Park intro chase: the runaway Shadow Mario (`TEMario`) drifts off his path, jams into a wall, then teleports forward past it — worse at higher G | The run-away escape state machine runs on the PER-RENDERED-FRAME AI path (`perform`→vtbl+0xC0 `checkController`→`consider`→nerve 0x10 `emRunAwayToNearestNode` @`0x80041620`): a FRAME counter (`+0x42a4`, inc @`0x80041AE0`) drives fixed thresholds, a per-frame lead-point march, and position SNAPS. The BODY moves per-SUBSTEP (`moveObject`→vtbl+0xC4 `playerControl`, 120Hz-pinned, FPS-invariant). At high FPS the schedule+snaps fire G× too early while the body has travelled 1/G of the distance → drift, wall-clip, then the schedule's own snap warps him forward. NOT anmrate (never calls SMSGetAnmFrameRate). | `runaway_gate()` C2 @`0x80041620`: gate the whole AI tick to 1-in-G rendered frames (native 60Hz) — skip path `blr`s from the cave (entry is `mflr r0`, LR live), counter in r12 (r0-as-rA is the literal 0), self-gated on framerate global `!=0.5f` | `bse_runaway_gate()` guarded (==2.0f) block, divisor G; emitted by `fpspatch --bse`, in `bse_build()` | AUTHORED 2026-08-28, verified `--check` (120/180/240 stock, 120/240 BSE); NEEDS-TEST (both engines) |

---

## §3 Per-item detail

### 1. M-portal glow (`sunshine-portal-glow-bug`)
**Symptom:** with the hack ON (60 AND 120), Delfino rainbow-M `TModelGate` portals stay
permanently dark and unenterable; at native 30fps they glow-on-approach.
**Root cause (final, after many reversals):** the glow is a balance of RISE
(`glow += 0.1` in `receiveMessage`, driven by `checkActorsHit` gated `!(unk58&3)`,
**30/sec realtime regardless of fps**) vs DECAY (`glow -= 0.02/0.025` in
`TModelGate::perform`, **per rendered frame**). At 120fps decay exactly cancels rise →
never lights. `TModelGate` TU is USA `0x801EAC64–0x801EC8C0`; `perform=0x801EB014`. The
gate's MASTER SWITCH is `perform`'s first check `if(!(0x70&1)) skip body`; bit set only by
`startOpen()`, which `loadAfter` does NOT call. Also `0x804167B8` is genuinely a framerate
value (NOT the sqrt constant; that was a wrong-r2 red herring; sqrt 0.5 is at `0x8040EBC8`).
**Shipped fix:** `PROXIMITY_GLOW` (distance-reimplemented proximity glow, ~354u radius,
XZ distance) + `FORCEOPEN` (C2 @`0x801EB034`+0x7 that calls the real `startOpen`). Both are
rate-independent. `--no-forceopen` respects story locks.

### 2. Camera look-up (`sunshine-camera-lookup`)
**Mechanism:** C-stick Y drives a 0..1 X-rot ratio at `CPolarSubCamera+0xA8`, lerped between
`mXAngleMin`(~+5°) and `mXAngleMax`(~+55°); the same ratio drives zoom/cushion so widening
it warps everything.
**Fix `$Camera look-up vN`:** hook B @`0x8002510C` banks below-floor stick overflow into an
extra-pitch accumulator; hook A @`0x80024D1C` subtracts it from final pitch. Scratch block
`0x800016F0` (magic `CMEX`). Frame-independent, bit-identical to stock until stick held past
the old limit. Evolved v1→v11 fixing: second-camera-object zeroing (gate on `this==gpCamera`
`0x8040D0A8`), ground-revision dive-stuck, Mecha Bowser regression (gate on return addr
`0x2C(r1)`, blacklist `0x80031108`). v10/v11 shipped. **Trap:** its 0x40-byte scratch
reaches to `0x800016F0+0x40`. Keep it clear of the fpspatch counter slots (see item 30).

### 3. FOV (`sunshine-fov-mod`, `sunshine-fov-mod-keep-enabled`)
USA `mFovy` is at CPolarSubCamera **+0x48** (JP is +0x30). A naïve write to mFovy fails
because `ctrlGameCamera_` overwrites `*mCurrentParams` from `mSaveKindParam[mMode]` every
frame. **Daily code = `$FOV 60` (NO `[kris]`), a TWO-hook code:** C2 @`0x8034A404`
(C_MTXPerspective-entry allow-list) + C2 @`0x802260CC` (`SetViewFrustumClipCheckPerspective`,
thresholds 4220/4260 → 4270=60.0, the one that actually widens the view). The single-hook
`$FOV 60 [kris]` does NOT move the gameplay camera; keep it defined-but-disabled. An UNGATED
entry-hook variant forces effect/screen-texture reprojections → heat-shimmer misalignment;
never re-enable it. **Rule: after any GMSE01.ini mutation, verify exactly ONE `$FOV NN` is
enabled.** Under BSE, the stock FOV must be DISABLED (its caller-whitelist breaks, causing
scene-vs-shimmer FOV mismatch seen live 2026-08-13 as "FOV only applies to the shimmer");
use `gViewportSetting` (coarse) if anything. The keep-FOV-enabled rule applies to the STOCK
kit only. Under the BSE trim, verify `$FOV 60` is NOT in [Gecko_Enabled].

### 4. Widescreen
Stock: `$Widescreen [gamemasterplc]` from the shipped Sys INI (60 code lines, sits late in
the list, so needs the code-cap relocation to run at all). **Under BSE:** write
`gAspectRatioSetting @0x8051E4D8 = 3` (WIDE 16:9) and set Dolphin `wideScreenHack=False`.
The stock `$Widescreen` fights BSE and must be disabled. Confirmed working online 2026-08-12.

### 5. Audio tempo + pitch (`sunshine-audio-fix`)
Two halves, both required: (1) **tempo**: Dolphin BINARY patch,
`SystemTimers.cpp GetAudioDMACallbackPeriod` × `MAIN_EMULATION_SPEED` when speed>1 (in our
build only; `~/Dropbox/sunshine-highfps-audio.patch`). (2) **pitch**: config
`AudioPreservePitch=True` (else the mixer does `in_sample_rate *= emulation_speed` and
pitches up 2x). Also `AudioBufferSize=136` (default 80 underran at level-load and looped a
"frozen chord"). Residual: streamed cutscene/intro audio (separate mixer path)
uncompensated. Engine-agnostic (build + config level).

### 6. BGM DSP voice-limiter coin-toss (`sunshine-music-cointoss`)
**Symptom:** 120fps level BGM silent as a per-load coin toss (SFX always fine).
**Cause:** `JASystem::TDSPChannel::updateAll` (`0x80314C60`) force-stops the lowest-priority
voice when `f32(history[0])/tick_gap < DSP_LIMIT_RATIO(1.1f)`; the tempo patch halves DSP
cadence vs emulated time, so the heuristic chronically misfires and kills every sequenced
BGM note at birth. **Fix:** `0440CDB4 00000000` (`DSP_LIMIT_RATIO=0` @`0x8040CDB4`). Plus the
tempo guard `BGM_TEMPO_GUARD` C2 @`0x8031B8C8` (substitute 1.0 for a 0.0 outer tempo
proportion across scene transitions). Both rate-independent, vanilla addrs, should work
under BSE.

### 7 & 8. Particle / flash parity + JPA-2x-at-240 (`particles()` in fpspatch.py)
`EmitterViewObj::perform` runs `for(i=SMSGetAnmFrameRate(); i>0; --i) emitter->calc()` on
CUE_CALC_ANIM; the stub makes `SMSGetAnmFrameRate=0.5 → fctiwz(0.5)=0` → **0 calcs → frozen
emitters** (the "flash-invisible on level reconstitute" bug). The gate injects `+1.0` on
gated ticks to advance the JPA world. **The divisor is the CONSTANT 2** because CALC_ANIM
fires ~120 Hz at every G and native JPA is 60 Hz (`120/2`). 3 hooks:
C2 @`0x802887A8` / `0x80288D30` / `0x80288DEC`, counting `gpMarDirector+0x5C`. The wrong
1-in-G form ran JPA at 120/G (M-portal atoms 2x-slow at 240). **Under bare BSE-120 this was
BROKEN** (stock bundle disabled): restored via guarded C2 at the SAME three addrs
(confirmed 2026-08-12). The level-load **decompose/recompose animation + "slide" effect
is STILL MISSING under BSE** (the particle parity fix did not cover it); needs its own
investigation (see item 23).

### 9. Blue coin timer (`sunshine-bluecoin-timer-fix`)
Spray-spawned blue coins (TCoin) vanish too fast because lifetime is a FRAME counter
(`mStateTimer` @TItem+0x104), not a stopwatch. Seeds: appear 120 + disappear 480 = 600 ticks
= 20s @30fps. **`$Blue coin timer v6`** C2 @`0x801BE880` (`TCoin::perform`'s `--mStateTimer`),
fps-gated, decrement on 3-of-4 substeps (¾-rate), measured 19s vs 20s. **Calibrated to this
machine's measured ~40 perform-ticks/sec at 120fps, NOT derived from G**, so fpspatch emits
it ONLY at 120 (`if bluecoin and g==2`). Two hard-won C2 lessons live here (every path must
converge on the branch-back word; don't clobber the store value r3). **Under BSE:** still runs
fast (stock fix removed): a v6-BSE C2 at the same addr, needs live re-calibration to ~20s.
**2026-08-12:** v6 emitted by `fpspatch 120 --bse` and installed in the INI but left
DISABLED. The ¾-rate assumes ~40 ticks/s; under BSE perform likely ticks 120/s, so the
correct BSE gate is probably keep-1-of-4 (invert the two addi paths). Time spray-coin
lifetime live, then flip the ratio and enable.

### 10. Race / countdown clocks (`sunshine-timer-fix`, `timerfix()`)
SMS clocks (blooper race, Piantissimo, countdowns, verdicts) are OS-tick stopwatch based:
they read `gpMarDirector+0xE8` via `OSCheckStopwatch` (`0x80348114`, exactly 4 callers). The
emulated timebase advances G× realtime → clocks run G× fast (2x at 120, NOT 4x; this is the
timebase family, distinct from frame-counter bugs). **`$Game clock fix v15`** C2 @`0x80348180`
(the single blr exit) divides the 64-bit tick result by G (shift for powers of two, long
division for 180), gated on `0x804167B8 == float(G)` so it's a no-op without the fps code.
Vanilla addr, re-enabled and works under BSE.

### 11. Petey vomit window (`sunshine-petey-vomit-window`)
Barf window ~4x too short (~1.2s vs ~4.7s). `TBossPakkun::changeBck` (`0x8009548C`)
special-cases bas idx 0x15 and overwrites frameCtrl+0xC with the RAW `mSLVomitAnmRate` param
(@`0x800955CC`), an absolute 30Hz rate that plays 4x fast at 120. **`$Petey v16`** C2
@`0x800955CC`: re-run the store, then if `0x804167B8==2.0f` do `addis -0x100` on the raw
float bits (exponent−2 = ×0.25). Self-disables at stock/180. **Superseded by `anmrate()`**
(item 27) which does `R/(2G)` generally. Disable v16 if enabling anmrate or Petey
double-scales. Vanilla addr, re-enabled under BSE.

### 12. Poink premature explosion (`sunshine-poink-corrected-diagnosis`)
Bianco Ep.4 Poink pig explodes mid-flight (never reaches Petey). Flight ends
Fly→Explosion at flyTimer ~8–11 EVERY time regardless of velocity, a time-based trigger
(a CUE_CALC_ANIM-driven counter reaching threshold 4x sooner at 120). The Explosion nerve is
pushed EXTERNALLY (not from the Poink's own Fly code). **`$Poink v14`** C2 @`0x800e5e44`
(TNervePopoExplosion::execute first tick): if mid-flight (+0xF0 bit0x80) AND flyTimer(+0x19c)
< **40**, revert spine+0x14 to the Fly nerve `0x8040d95c`, set spine+0x20=1, `bctr` to
epilogue `0x800e6000`. Threshold 36 fell short; 40 lands it. The bare `cmpwi 40` is
rate-INDEPENDENT (flyTimer runs on substep-invariant spine ticks). v13 (a collision-latch
gate @`0x800e6228`) was WRONG: bit 0x80 never clears. NEEDS-TEST under BSE.

### 13. Noki pollution perf + goop (`sunshine-noki-pollution-perf`, `noki_gate`/`noki_copy_gate`)
Noki Ep.1 caps ~105fps: pollution DEGREE-COUNTING runs per rendered frame and does
synchronous GPU→CPU readbacks (`ReadTexels`/`GXReadPixMetric`/`PeekEFBColor` ≈ 39% of the
emu thread), 4x too often at 120. Native 30 Hz work, divisor **FPS/30 = 2G**.
**v3 (current):** gate ONLY the two counting call-sites inside `TPollutionManager::perform`
(`0x8019D8C8`): `0x8019D8F0` countObjDegree + `0x8019D91C`/`0x8019D934` countTexDegree,
while the layer-0 model-stamp DRAIN (`0x8019D90C`) runs EVERY frame. Counters: obj
`0x800016E0`, tex `0x800016E4`. **REQUIRED companion `noki_copy_gate`** C2 @`0x802F8CF8`:
gates `TEfbCtrlTex::perform`'s EFB→pollution-image copy to the same cadence
(discriminate pollution layers by `mTexFmt(+0x30)==0x28`), else the map snapshots black EFB
and goop vanishes. v1/v2 blr'd the WHOLE perform (skipped the drain, batching stamps, causing
the M-portal ripple-lateness AND the Bianco J3D self-loop freeze that OOM'd Metal to 64GB); v3
retires the old `noki_dedupe` because per-frame drain prevents batches. **Under BSE:**
re-enable the v3 6-block fpspatch version (NOT the obsolete standalone v1).
**2026-08-12:** done. Guarded 5-block version (`fpspatch 120 --bse`, guard `*0x804167B8
== 2.0f`, guard-fail = call runs every frame = stock) installed + enabled. NEEDS-TEST.

### 14. HUD perpetual stars (`sunshine-hud-stars-bug`)
Star sparkles never stop after unpause. TWO leaked JPA emitters, dominated by the pause
menu's item-highlight emitter: at 120fps the director exits pause before the menu's close
anim reaches the `mFadeAnim==0.0` deletion tick, leaving the emitter alive and emitting
forever (one leaked per pause). **`$StarFix v4`** = v2 (`pauseOut` @`0x8014A850` stops
con+0x124 + pause emitter) + v3 (@`0x80155D8C` stops the previous bounce emitter before
each re-create) + watchdog (@`0x80324EB8` in `JPAEmitterManager::calcBase`: if
mgr==`0x8040E1E4` && maxFrame==0 && !stopped && age>600 → STOP_EMIT, catches the 3
stranded banner emitters). NEEDS-TEST under BSE (safe once particles are confirmed 60Hz).
**2026-08-12:** guarded v4 (`fpspatch 120 --bse`) installed + enabled. NEEDS-TEST.

### 15. Repeating-SE 30Hz gate (`sunshine-cogwheel-creak-fix`, `se_frame_gate`)
ALL repeating SEs (FLUDD hover putter, Noki urn rope creak `MR_TSUBO_PULL`, Gooper Blooper
tentacle `BS_GESO_TAKEN_HAND`, etc.) run FPS/30 x too fast. Actors request them every move
tick; the audible cadence is set by JAudio's per-rendered-frame SE process PAIR:
`checkNextFrameSe` (`0x80305204`) + `sendPlayingSeCommand` (`0x80305958`). **Fix:** gate BOTH
to 1 rendered frame in FPS/30 via an early `blr`. Send hook owns counter `0x800016E8`; check
hook tests counter+1 without storing (it runs first). Do NOT gate SE at call sites: the
superseded per-site cogwheel v1 (@`0x801DA1E8`/`860`) starved the keep-alive window and
chopped every SE at 2x native. Ear-test still pending.
**2026-08-12:** guarded pair (`fpspatch 120 --bse`) installed + enabled for BSE. Ear-test
pending on both engines.

### 16. SaveBox Continue-on-top (`savebox-continue-top-v1.txt`)
QoL: makes "Continue" the top/default row in the in-level save box. Four `04` writes flip the
BMG message ids (0x1C↔0x1D) at `0x80162FC4/FE8/163074/098` (label swap) + C2 @`0x8015CAC0`
in `waitForSelect2` case 5 (semantic swap of unk2E9). Vanilla addr, works everywhere.

### 17. Tank controls (`tank-controls-v8.txt`)
QoL opt-in. v8 (no forced pivot): `|theta|<0x6000` front cone = uncapped steer `theta>>6`;
`>=0x6000` rear cone = latched turnaround. Pure integer, 30 words. Hooks the checkController
`mIntendedYaw` region. Supersede lower versions when enabling.

### 18. FLUDD aim invert (`fludd-aim-invert-v3.txt`)
QoL opt-in "up aims up". Word 1: `TNozzleBase::calcGunAngle` squat branch @`0x8026D17C`
(`add→subf`). Word 2 (v2): `ctrlLButtonCamera_` @`0x80029208` (`fneg f30 → fmr f30`) to fix
the first-person/zoom vertical. Kills only the vertical negate; horizontal preserved.
**v3 (2026-08-13):** + word 3 `040310DC FFA00090`. The Mecha Bowser fight uses a SEPARATE
camera mode (`CAMERA_MODE_JET_COASTER` → `ctrlJetCoasterCamera_` @`0x80030E7C`,
`tinkoopa_camera`), which is why v2 missed it. The flipped word is the fight-only vertical
stick negate (`fneg f29,f0 → fmr`) feeding `rotateX_ByStickY_`; provably fight-exclusive so
a bare 04 is safe. Enable v3 OR v2, not both.

### 19. Animal movement rate (`sunshine-animal-movement-rate`, `animal_speed`/`animal_duration`)
Delfino kamome (`TAnimalBird`) are shared-anim enemies: `performShared` calls `moveObject`
every substep with no final-frame gate, so speed = `speed × SMSGetAnmFrameRate` at 120 Hz.
The `ANMRATE_STUB`(0.5) is right for anim rates but WRONG for these substep-paced speeds:
birds move at exactly **1/4 speed at every patched G** (accel is rate², 16x low). A second
bug: nerve duration helper @`0x8000AB38` (`N × 1/AnmFrameRate`) made every phase 4x longer.
**Fix:** `animal_speed()` + `animal_duration()` ×4 restores, shipped with every `substep`
bundle. If `substep` is off under BSE these break.

### 20. Skid U-turn / turn-around (`sunshine-turnaround-skid-bug`, `turnaround_fix`)
Running U-turn (flip stick while dashing) nearly impossible under the bundle. The threshold
(`|mIntendedYaw−mFaceAngle.y|>0x471C` with vel≥10) is rate-invariant (CUE_MOVE), but STICK
FRESHNESS is not: stock reads the pad at 30 Hz (stale jump guarantees the 100° gap); under
the bundle the pad reads ~120 Hz so `doRunning`'s yaw pursuit tracks THROUGH the flip.
**Fix:** hook `running()`'s check @`0x8025AF64` and compare against `mFaceAngle.y` from FOUR
sim ticks ago (a 4-deep ring @`0x80001724`, indexed by substep counter). The delay is the
CONSTANT 4 (sim ticks pinned 120 Hz). Reseed guards for state-change and a second TMario
(Shadow Mario). Playtest pending.

### 21. Shine-select cadence (`select_gate`, `select_grad_gate`)
The in-stage episode/shine select is run by `TSelectDir`, a separate director that fires
CUE_MOVE|CUE_CALC_ANIM once per RENDERED frame with no TMarDirector gating: cursor repeat
~3x fast at 360, and the 3D shines flicker. **Fix:** hold the SIM tick to 1 frame in
`ceil(G/2)` (a 120 Hz cadence) by hooking `TDirector::direct`'s MOVE-pass bl @`0x802F7DBC`
(vtable-gated to `TSelectDir` `0x803C0EF0`), calling testPerform with CUE_CALC_ANIM ONLY on
gated frames (keeps J3D shine entry alive). REQUIRED companion `select_grad_gate`
@`0x80175584` gates the background color-cycle to 30 Hz. Also adds a TSelectDir case to
`input_latch`. Only emitted at G>=3 (G=2 was always correct).

### 22. Input latch / dropped inputs (`input_latch`)
`gameLoop` calls `read()` once per DISPLAYED frame, so at high FPS an edge is reported
several times per sim step. Hook @`0x802A600C` skips the pad read on frames that won't
advance the sim (remainder < 5G−10) and zeroes `mTrigger(+0x1C)`/`mRelease(+0x20)` on all 4
pads, leaving held state intact. Gate on TMarDirector vtable `0x803DF0C8`. Confirmed
in-game at 180fps. Omitting it drops ~1-in-3 edge inputs. Unreachable at G=2 (returns None).

### 23. Wipe pacing + decompose/recompose (`wipe_pace`, `wipe5_swap`; `sunshine-wipe-morph-perf`)
All Hx wipes are frame-counted for 30fps rendering, so at high fps they play 2G× too fast
(the level-entry decompose/recompose = 55ms instead of 0.67s at 360). **`wipe_pace`** gates
the wipe clock to 1-in-FPS/30. The Hx_Test5 128px half-scale morph does 80 EFB copies/frame
and tanks fps at G>=3; the tile-morph optimization (`wipe5_opt`+`wipe5_smooth`) was REJECTED
in playtest (wrong-scale chunks + black slabs), so the DEFAULT at G>=3 is `wipe5_swap`:
redirect wipe ids 5/6 to Hx_Test4 (fn-table 04s @`0x803C12B0/B4`). **Under BSE the
decompose/recompose ANIMATION + "slide" effect is STILL MISSING** (the particle parity fix
did not restore it); it needs its own investigation.
**2026-08-12:** working hypothesis: it is not missing, it is the un-gated wipe playing
4x fast (~0.17s at BSE-120) and reading as absent. Guarded `wipe_pace` (1-in-4, guard-fail
= stock ungated) installed + enabled via `fpspatch 120 --bse`; no wipe5_swap (G>=3 only).
NEEDS-TEST: enter a level online and watch for the ~0.67s decompose/recompose.

### 24. Audio pump / 240fps total silence (`audio_pump_gate`)
At 240 all music goes silent + continuous SEs flicker-restart: `MSound::mainLoop`
(hook @`0x80014DA8`) processes SE requests at render rate, outruns the 120 Hz substep
request rate, thrashes the 64-voice pool, and steal-kills every BGM note at birth. Gate to
1-in-FPS/30 (counter `0x800016F8`). Render-rate class.

### 25. THP movie pace (`thp_pace`)
The silent M-portal PREVIEW movies play G× fast because SDK `THPPlayer` paces off VI
retraces, which fire G× wall speed under EmulationSpeed=G. Divisor `5994*G`. Audio-mastered
cutscene THPs are EXCLUDED via the `audioExist` discriminator to keep A/V sync.

### 26. Ricco hook slide-clank (`sunshine-riccohook-womp`, `riccohook_se_gate`)
Near Ricco Harbor cable hooks: "womp womp, staticy, faster the more fps". `TRiccoHook::perform`
(`0x800c7a54`) requests `CRANE_SIDEMOVE1/2` (0x3034/5) every tick once `mTimer(+0x154)` hits 0
and never re-arms. The 30 Hz audio pump alone does not tame it, so a dedicated gate keyed on a
rendered-frame clock (1-in-FPS/30) on the pump counter.

### 27. anmrate raw setters (`anmrate()`, `sunshine-highfps-bug-surface`)
The real high-fps bug surface is the ANIM path (~13 PARAM functions → 15 raw-param→frameCtrl
rate stores that bypass the getter). Nerve/spine timers are substep-invariant: a global
mTime÷G hook would REGRESS ~200 correct timers; do not build it. **`anmrate()`**
emits 15 hooks scaling a raw rate by `R/(2G)` via
`lfs fS,-0x3c8(r2); fadds fS,fS,fS; fdivs fR,fR,fS`, self-disabling (stock G=0.5 → 2G=1.0 →
no-op). At 120 = ×0.25 = exactly Petey v16 (which is in the set and thus superseded).
Petey confirmed; the other 14 hooks (clusters `0x8013cXXX`, `0x80205354`, `0x80117xxx`) are
NEEDS-TEST in-game. Audit tooling: `animrate_audit.py` (source), `animrate_disasm.py`
(binary), `animrate_merge.py` (master worklist).

### 28. Shimmer / heat-haze (`sunshine-shimmer-pace`)
Heat mirage pulsates 4x fast (constant, not G-scaled; FOV mod is NOT the cause). `TShimmer`
(`perform=0x8019F83C`) advances its warp BTK via a private `J3DFrameCtrl` @+0x58 pinned at
1.0 in `load()`, never scaled through `SMSGetAnmFrameRate`: substep MOVE pass at 120 Hz =
4x fast. `ANMRATE_SITES` can't cover it (no rate STORE to hook). Candidate v1
(`shimmer-pace-v1.txt`): C2 @`0x8019F89C` re-applies rate 0.25 to ctrl+0xC each MOVE tick;
self-gates (skips when `*0x804167B8 == 0.5f` stock).
**2026-08-12:** folded into fpspatch as the `SHIMMER` constant, default-on in the stock
bundle (`--no-shimmer` to omit) and included in `fpspatch 120 --bse`; installed + enabled
in the live INI. NEEDS-TEST in-game (both engines).

### 29. Talk-init debounce (`TALK_INIT_FIX`)
Starting a conversation (B near NPC) is gated by a two-phase bit0→bit1 handshake on
director+0x128 across movement_game (per-substep) and changeState (per-frame). Under the
substep retune those cadences diverge: talk initiation structurally impossible at 360,
~50% dropped at 180. **Fix:** retarget the test @`0x8029A908` from bit1 to bit0
(`0429A908 540007FF`). Behaviorally identical at G=2/stock, emitted whenever substep is;
rate-independent, no cave words.

### 30. Low-arena scratch collision (`sunshine-lowarena-scratch-collision`)
Gelato Beach sand-castle secret-entry soft-locked at 240: a wipe never ended because the
camera look-up code's 0x40-byte block @`0x800016F0` stomped the fpspatch counters. **The
authoritative low-arena slot map:** Noki obj `0x800016E0`, Noki tex `0x800016E4`, SE frame
`0x800016E8`, camera scratch `0x800016F0` (reaches +0x40), wipe `0x800016F4`, audio-pump
`0x800016F8`, turnaround ring `0x80001720`, camera-code block `0x80001730+`. Respect this
map when allocating new scratch.

### 31. BSMSO idle→controller-settings crash (`sunshine-bsmso-mac-integration`)
Online-only: entering controller settings while idle threw an ISI exception. The ghost
bot's unbounded `AnimId` ramp indexed past `gMarioAnimeData[411]` in
`TMario::setAnimation`. **Fix:** clamp `anim_id %16` in `ghost_bot.py` and sanitize
`anim_id<=410` in `bridge.py`. FIXED 2026-08-12.

### 32. Fruits-boat / boids (`sunshine-fruitsboat-pacing`)
User suspected fast plaza gondolas/boats. `TFruitsBoat` one mode is stock speed,
the other 4x SLOW; `TBoidLeader` shoals are 4x fast at code level but user confirmed
"normal" in-game. WONTFIX, no gate shipped.

### 33. Sun lens-flare probe (`SUN_PROBE`)
`0402E28C 60000000` NOPs the 17-GXPeekZ-per-frame occlusion sampler. OPT-IN only
(`--sun-probe`): recovers no measurable frame time (the Noki stall was the pollution
readback) and breaks the flare (draws through geometry). Off by default.

### 34. Widescreen wipe fix
`$Widescreen wipe fix v2`: a real but independent copy-vs-draw misalignment in 16:9,
distinct from the wipe5 morph. User reported "not fully working"; kept enabled to observe.
PENDING.

### 35. Ghost puppet locomotion + despawn (online)
Online puppet "floats" (not playing locomotion anims), and departed puppets froze forever
(no despawn on leave). **2026-08-12, implemented in `sunshine/bsmso/mac-online/`:**
- **Despawn:** the server never sends PlayerLeft (id 13). Departures arrive as a
  RosterSnapshot (id 6) missing the player. `netclient.py` now diffs old-vs-new roster
  slots in BOTH handlers and fires a new `on_player_left(slot)` callback; `bridge.py`
  `_on_player_left` zeroes the slot's 64-byte snapshot (connected=0), emits a RosterHud
  **Kind=2 Disconnected** event (via the new shared `_emit_roster_event`, mirroring the
  Windows bridge's `RemoveRemoteSnapshot`), and evicts `_known_slots`/`_last_remote`.
  Note: the old `parse_player_left` (payload[0]-as-slot) was wrong. Id-13 carries a
  roster blob.
- **Locomotion:** `ghost_bot.py` now sends true circle-derivative `vel_x/vel_z`, a ~30fps
  advancing `anim_frame`, and `_select_anim(speed)` with `ANIM_IDLE=0xC3` (confirmed from
  Mario.hxx). **`ANIM_WALK`/`ANIM_RUN` are unknown**: no walk/run ids exist anywhere in
  the repo; capture live by reading `TMario::mAnimationID` while walking/running, then fill
  the constants. Until then the bot animates idle instead of cycling garbage ids.
NEEDS live ghost self-test (join, move, leave: puppet should animate then despawn).

### 36. PC 240fps online (fork built, boot-test pending)
BSE has NO FPS_240 case: `mFPSValue=3` hits uninitialized paths, so 240 online needed a
BSE SOURCE mod. **2026-08-12: the fork exists.** BSE v4.0.0 rebuilt on the Mac with
FPS_240/280/320 (`sunshine/bsmso/bse-highfps-240-280-320.diff`, artifact
`BetterSunshineEngine-highfps-v400.kxe`, installed in `BSMSO-GMSE01-highfps.iso`). See
`sunshine-bsmso-mac-integration` memory for the build recipe. The new kxe shifts module
data: `mFPSValue` is NOT at `0x8051E528` in the highfps ISO. bridge.py's hardcoded poke
and `$BSE Force 120 FPS` only fit the OLD kxe; re-scan if the Mac runs the new ISO. The
0x804167B8-based guards in the BSE companion are unaffected (fork writes FPS/60 there; at
240 they read 4.0 and self-disable: 240 would need FPS/30=8 divisors, a future
`fpspatch --bse` variant). Two-machine cross-play test still to do.

### 37. Pachinko FLUDD "suction" (`HANDOFF-PACHINKO-BUG.md`)
Delfino pachinko secret at 120fps: hovering toward the top-left red coin pulls Mario
toward the middle / "sucks" him into the blue coin. DIAGNOSIS ONLY, never reproduced
under instrumentation, no fix landed. The naive "rate-dependent hover" theory is ruled
out (CUE_MOVE is substep-pinned at 120Hz at every display rate); remaining suspects in
the handoff: per-render splash/particle pushes at pegs (4x as many), input-poll cadence,
or a spawn/count effect. Was MISSING from this catalog until 2026-08-13.

### 38. Menu key-repeat 4x under BSE (`menu-repeat-bse-v1.txt`)
Holding a direction in menus races through options under BSE-120 (save-select, in-level
pause). `TMarioGamePad::reset` (@`0x802A897C`) sets button-repeat delay/interval as
`20/6 ÷ SMSGetAnmFrameRate()` = 10/3 **ticks** (correct counts); the fault is the ticker:
`JUTGamePad::CButton::update` advances once per `read()`, which BSE runs ungated at 120Hz
(stock fpspatch was immune because the ANMRATE stub yields 40/12 ticks AND input_latch
gates read()). Delfino-pause "immunity" is an artifact: with ≤2 menu items every repeat
re-selects the same item (no sound/motion), so the bug is invisible there, confirming the
shared mechanism. **Fix:** C2 @`0x802A89C8` (last insn before the single-caller
`setButtonRepeat` @`0x802C9A4C`): ==2.0f guard, then `slwi r5/r6, 2` (×4 → 40/12) and
re-exec the original `addi r4,r4,0xf`. Menus only: `mRepeat` is consumed solely in
`updateMeaning`'s menu-nav branches; trigger/release edges untouched.

---

## Current-state snapshot (2026-08-12)

**Stock 120fps kit (fpspatch bundle):** all of §3 items 1–30 shipped and mostly confirmed at
120fps on the Mac; the >120 tests are confounded by the hardware ceiling (§1.2). Shimmer
(28) is now in the bundle (NEEDS-TEST); Widescreen-wipe (34) is the open cosmetic item.

**BSMSO online kit (BSE):** 120fps online + widescreen + ghost self-test CONFIRMED working
on the Mac 2026-08-12 via BSE-native pokes (mFPSValue=2 @`0x8051E528`, aspect=3
@`0x8051E4D8`, `wideScreenHack=False`). Particle parity restored via guarded C2 at the 3
parity addrs; Game-clock v15 + Petey v16 re-enabled; FOV disabled; idle→settings crash
FIXED (anim clamp).

**2026-08-12 (later):** `fpspatch.py 120 --bse` now generates the whole BSE-120 companion
bundle (`sunshine/research/codes/bse120-companion-v1.txt`, validated by `--bse --check`).
Installed + ENABLED in the live INI: guarded Noki v3+copy (13), StarFix v4 (14), wipe_pace
(23, "missing" decompose/recompose is hypothesized to be the wipe at 4x), SE frame gate
(15), shimmer (28). Installed DISABLED: blue-coin v6 (9, ¾-rate needs BSE recal, likely
1-of-4). Despawn-on-leave implemented + ghost locomotion scaffolding (35). **Never enable
the companion alongside the stock 120 bundle: same C2 hook addrs.**
**Still open under BSE:** live tests of all of the above, blue-coin recal (9), Poink v14
re-test (12), SE ear-test (15), walk/run AnimId capture (35), PC 240 BLOCKED (36).

**2026-08-29 (landing lag CLOSED — it was the jump-chain family itself):** two
findings. (1) **The fix had never executed.** The v3 code was in the live
`GMSE01.ini` `[Gecko]` and absent from `[Gecko_Enabled]` on a freshly-written
INI, because `smslaunch/config.py`'s `BASELINE_FIXES` row gated it
`verified=False`. v1→v2→v3 were authored, `--check`ed and documented across two
days without one line running in-game — *when a fix "doesn't work", diff
`[Gecko]` against `[Gecko_Enabled]` before re-deriving anything.* (2) **There is
nothing to fix.** `mStatusTimer` is the ONLY timer in `jumpSlipEvents`
(`lhz r5,0x86(r3)` @0x80258D50 vs `lha r0,0(r4)` @0x80258D60), so the chain
window IS the post-landing slip lockout: stock BSE-120 = 16 ticks @120Hz =
**133ms** (snappy — vanilla is 533ms), v3's ×2 = 267ms, v1/v2's ×4 = 533ms = the
reported stun. Kris live at BSE-120 with the family disabled: *"landing lag
didn't happen on restart."* **Confirmed-good landing config = the family OFF.**
v4 splits v3's welded block into `$Landing momentum BSE-<fps> v4` (the
jumpSlipCommon 0.98/tick `mForwardVel` retune, toggle `landingmomentum`) and
`$Jump-chain window x2 BSE-<fps> v4` (the three chain-record writes, toggle
`jumpchain`) so they can be A/B'd — they pull opposite directions on landing
feel. **Both default OFF.** John's triple-jump complaint (#39-adjacent) is
UNFIXED by choice: one counter cannot give both an easy triple jump and a snappy
landing; enabling `jumpchain` is a per-client trade, not a shared-code decision.
A real fix needs a second timer. `HANDOFF-JUMPCHAIN-BUG.md`.

**2026-08-28 (BSE-60 companion):** `fpspatch.py --bse` generalized to emit an
**FPS_60** companion bundle (`bse_supported` now admits G=1; `bse_sim_fps`
corrected to the CONSTANT 120 Hz it always was under BSE — the old `min(fps,120)`
under-counted the substep-class divisors at 60). The "known-good 60 fps ISO" is
BSE FPS_60 = 2x native, so it carries the render-class (divisor **2**), anmrate
(**×0.5**) and substep-class (blue-coin 1-of-4, shimmer 0.25, bird k2,
jump-chain ×4) bugs — but NOT the particle-parity/boid (CALC_ANIM is native
60 Hz at FPS_60 → `bse_parity`/`bse_boid` return None), the game-clock
(EmulationSpeed=1 → `timerfix` None) or the substep-pin fixes. `--check` asserts
those three are absent. Artifact `research/codes/bse60-companion-v1.txt`;
Windows handoff `bsmso/WINDOWS-60.md`; the whole PC chain
(`play240.ps1 -Fps 60` → `switch_rate.py --fps 60`) already accepted 60 and now
produces a correct bundle. NEEDS-TEST: nothing at FPS_60 has been booted;
highest-risk call is the parity omission (watch for frozen/half-speed particles).
No custom Dolphin build needed for audio at 60 (EmulationSpeed=1 → stock audio
is correct).

**2026-08-13:** BSE regression day. Root-caused the "60fps 2x speed" (BSE cold-boots
FPS_30/aspect-0 every launch; the prior session ended with the working old-ISO+bridge setup
torn down for fork-ISO testing). New tooling: `set_bse_fps.py` (no-stage RAM poke,
fps+aspect before scene-init) + `play120.sh` (one-command launcher, `--ghost` for the full
online stack). bridge.py pokes are now discovery-validated (no blind writes; `--fps` arg).
`$FOV 60` disabled under BSE (shimmer-only mismatch seen live). Bianco Ep.1 crash
A/B-isolated to the BSE Noki gate: DISABLED (item 13; code statically exonerated, suspect
low-arena scratch vs Kuribo runtime). Companion v2 adds BSE-guarded/self-gated: clock v15
(10), anmrate (27, covers Petey 11 + Gooper), animal ×4 (19), Poink v14 (12): all
installed+enabled, NEEDS in-game test: birds, Petey fight, Poink balloons, Gooper Blooper,
race timers.
