# Puppet Hover-Burst render hook — implementation design (#1, visual)

**Goal:** when a remote player does a moveset **Hover Burst** (or spray burst), make the
puppet on our screen show the burst FLUDD water instead of the wimpy default hover mist.
Visual only; goop-clearing is a separate job (#2, see bottom).

Status 2026-08-28: RE complete, burst signature confirmed by live capture. This doc is
the build spec. Related memory: [[sunshine-bsmso-puppet-fludd-cosmetic]].

## Confirmed facts (capture + `_BSMSO.kxe` disasm)

**Burst signature on the wire** (from `capture_burst.py`, `/tmp/burst-capture2.log`):
- nozzle = hover: wire `NozzleId & 0xF == 4` (wire byte `0x44` = `0x40|4`)
- `VfxFlags` has WaterSpray (bit 0) set
- action/nerve = **`0x0000088b`** (anim **86**); recovery frame = `0x88d`. Normal hovering
  never produces `0x88b`. (Spray-nozzle burst analog: emit nerve `0x88c`; spray nozzle
  render uses actions `0xc008220/0xc008222`, anim 150/152.)

**Why puppets show plain spray / no burst:** puppet FLUDD water is **cosmetic-only**. The
only real `emit__9TWaterGunFv` (0x80268f98) call is at `_BSMSO` code+0x7338, behind
`if (isPuppet) skip` (the `0xe03c` "is this one of the 10 puppet marios?" gate at code+0x72a8).
Puppets render water via `TMarioParticleManager` cosmetic emitters, not real collision water.

**Puppet FLUDD render seam:** `_BSMSO` code+**0xf254** is the puppet "FLUDD emitting" render.
It: reads the remote struct `r29` (snapshot fields at +0x21, +0x26=VfxFlags, +0x140/0x142
intensity, +0x5a), temporarily forces the puppet gun nozzle (`mFludd+0x1c84`) to `3` to
render, emits particle **`0x10d`** bound to the gun emit-mtx (code+0xf3e4), conditionally
emits the spray cosmetic **`0x1d4/0x1d5`** (calls code+0x108a8 @0xf42c), then code+0x10954.
Gated at code+0xf354 on intensity `f31` derived from snapshot byte `r29+0x142` (`ble → skip`).
Nozzle decode is correct elsewhere (code+0xbab8 masks `NozzleId & 0xF`, calls `changeNozzle`).

**Deploy path:** `_BSMSO.kxe` is a kuribo mod at
`/Applications/gamecube/bsmso-work/bsmso-root/root/files/Kuribo!/Mods/_BSMSO.kxe`, loaded
alongside `BetterSunshineEngine.kxe` + `BetterSunshineMoveset.kxe`. ISO is rebuilt from
`bsmso-root/`. Toolchain = CodeWarrior/clang + `KuriboConverter.exe` under Wine
(`bse-fork/tools/*.exe`, `bse-fork/build-mac/*.o` prove it builds here).

## Two architectures (the decision)

### A. Companion kuribo module (recommended)
A new small `.kxe` dropped in `Kuribo!/Mods/` next to the others. Registers a per-frame
`Player::addUpdateCallback` (runs for all marios incl. the 10 puppets). Each frame, for a
puppet whose transmitted state = {hover nozzle, WaterSpray, nerve `0x88b`}, emit a burst
effect on that puppet's gun (strong downward `emitAndBindToMtxPtr` of the burst particle,
or drive the puppet gun's emit-mtx). Additive; does not touch the stripped `_BSMSO` binary;
byte-for-byte reversible (delete the file). **Also the natural home for #2 later** (emit real
`TWaterGun::emit` on the puppet during the burst window → real water → clears goop).
Cost: must get the Wine build toolchain green (compiler + KuriboConverter + kxe link) and
learn the BetterSMS `Player::getData`/callback API (already imported by the moveset — we have
its CRCs). Read burst state either from the puppet `TMario` (anim/nerve/`mFludd+0x1c84`) or
from the comm buffer remote snapshots (anchor `0x817FC000`).

### B. In-place patch of `_BSMSO.kxe` (fewer moving parts, more fragile)
Binary-patch the puppet render at code+0xf254 so that when the remote nerve == `0x88b` it
emits the burst particle at full strength (bump the intensity / add a stronger downward
emit). No compiler needed, but: KXER has no spare section, so *adding* code means extending
the code segment + fixing the KXER header/relocs (kxdump parses but doesn't write back yet);
*in-place* edits (change an immediate, force the intensity gate, swap a particle id) are
possible without growing the file but give a cruder result. Not reversible without keeping
the original. Harder to also solve #2.

**Recommendation: A.** Cleaner, reversible, extensible to goop-clearing, and matches how the
mod stack is already composed. B is a fallback if the Wine toolchain proves unworkable.

**Toolchain confirmed working:** `bse-fork/mac-build.sh` compiles all BSE-fork sources with
the vendored Wine clang (`--target=powerpc-gecko-ibm-kuribo-eabi`), relocatable-links with
lld + `linker.ld`, and converts ELF→KXE via `KuriboConverter.exe`. A companion module reuses
this exact pipeline (its own source dir + linker script), or we add one source file to the
BSE fork itself (we already ship `BetterSunshineEngine.kxe` in the BSMSO ISO). BetterSMS API
(callbacks, `Player::getData`) headers are in `bse-fork/include/BetterSMS`.

### RESOLVED 2026-08-28 via solo loopback (server + bridge.py + ghost_burst.py)
- **Baseline reproduced:** a puppet fed {nozzle `0x44`, vfx `0x03`, act `0x88b`, anim 86}
  renders as a **plain FLUDD hover** on the observer — no burst (user-confirmed on screen).
- **Signal delivery confirmed:** comm remote slot shows the burst landing in-game
  (`noz=0x44 &F=4`, `anim=86`, `act=0x88b`, `vfx=0x03`). So the module can read the burst
  from the **comm buffer remote slots** (offset `112 + 64*k`, `action_id` @ +0x24).
- **Test harness:** `ghost_burst.py --mode toggle` parks a puppet next to you cycling
  HOVER↔BURST; reuse it to validate every build. Bring up: `run_server.sh`, then
  `python3 -u bridge.py --server 127.0.0.1 --name Kris --fps 120 --aspect -1`, then
  `python3 -u ghost_burst.py --server 127.0.0.1 --name Burst --mode toggle`. NOTE: start the
  bridge only on a **fresh** boot in a stable stage (a marathon-session game crashed on the
  first bridge write once).

### REMAINING design unknown: how does the fix reach the puppet TMario?
`_BSMSO` imports only `getData` + one `addUpdateCallback` — it drives the 10 puppets in its
own loop, so a companion module's BSE `Player::addUpdateCallback` likely fires for the LOCAL
player only, NOT the puppets. Options to emit on puppets:
- Companion module with a **Stage/Game update** callback that reads the comm buffer remote
  slots and, for each burst slot, finds the puppet `TMario` (needs a way to enumerate the 10
  puppet marios — `_BSMSO`'s puppet array, located at runtime) and emits.
- **In-place patch (B) of `_BSMSO` 0xf254**, which already holds the puppet + snapshot +
  emit machinery — add `if (snap nerve == 0x88b) emit burst`. More direct for *this* fix.
This is the next thing to settle before writing the callback.

### RESOLVED 2026-08-28 — how to reach a puppet to emit on it (the hard core)
- **Toolchain works:** `bse-fork/mac-build.sh` builds `BetterSunshineEngine.kxe` (exit 0,
  585 KB). A source-built module is viable.
- **BSE callbacks DON'T reach puppets.** `playerUpdateHandler` is `SMS_PATCH_BL`'d at the
  game Mario-update site (`0x80245134`); it fires for the LOCAL player only. `_BSMSO` drives
  puppets in its own loop, bypassing that site. So a companion module's
  `Player::addUpdateCallback` won't see puppets.
- **Puppets are `_BSMSO`-owned, interpolated, heap-allocated.** `_BSMSO` keeps an array of
  **0x150-byte per-puppet records** (stride confirmed by the `0xe03c` puppet-check loop),
  each embedding the 64-byte snapshot (vfx @ +0x26) + render state (+0x140/+0x142) + a puppet
  `TMario*`. Iterated at code+0x77a4 → render `0xf254(mario, record, vfx)`. The record array
  sits in MEM1 (game heap) at a **non-fixed** address; puppet `TMario` position is lerped, so
  it does NOT match the comm snapshot position (position-scan fails to find it).
- **Consequence:** there is **no quick byte-patch.** A module→game call (real
  `emit__9TWaterGunFv`) needs a KXER REL24 relocation, which a raw byte edit can't add. The
  three real options, all substantial:
  1. **KXER code-cave patcher for `_BSMSO.kxe`** — extend the code section, add a reloc for
     the `emit__9TWaterGunFv` call, and redirect the puppet render (`0xf254`) to run the real
     emit when the record's nerve == `0x88b`. Deterministic; needs a KXER writer (kxdump
     currently only reads; format spec in `tools/kuribo-src/.../kxer/Binary.hxx`).
  2. **Companion module + runtime discovery** — new `.kxe` with a Stage/Game update callback
     that locates `_BSMSO`'s 0x150-record array (scan/heuristic), and for each burst record
     calls `emit__9TWaterGunFv` on that puppet's `mFludd`. Cleanest long-term (also does #2
     goop-clear), but the array-discovery heuristic is the fragile part.
  3. **Rebuild `_BSMSO` from source** — we don't have it (upstream binary). Not available.

**Recommendation:** option 1 (KXER code-cave patcher) — most deterministic, self-contained,
and it puts the emit exactly where the puppet+gun already exist. Milestone-1 experiment even
before gating on `0x88b`: redirect the cosmetic spray emit at `0xf42c` to the real emit for
*all* hovering puppets, confirm real water + goop-clear appears, then add the `0x88b` gate.

### (superseded) OPEN QUESTION that gated the callback design
A per-frame BSE callback runs per-`TMario`. To fire the burst it must detect, on a **puppet**
TMario, the burst state. Need to confirm what `_BSMSO` actually writes onto the puppet
`TMario` vs. leaves only in the comm snapshot:
- **If** the puppet's real nerve/anim + `mFludd->nozzle(0x1c84)` reflect the burst (anim 86,
  hover) → callback can detect it straight off the `TMario` (simplest).
- **Else** the `0x88b` nerve lives only in the comm remote-snapshot (`remote[k]+0x24`) → the
  callback reads the comm buffer (anchor `0x817FC000`) and maps `TMario`→slot.
Resolve by observing a live/loopback puppet's `TMario` during a burst (bridge.py +
ghost_bot.py replaying a `0x88b`/hover snapshot, or a real second player). This is the next
concrete step regardless of architecture.

## First milestone (either path)
Make a puppet in the burst state emit *any* clearly-visible burst water on our screen
(correctness of shape/strength second). Test loop: patch/build module → rebuild ISO → boot →
have a real or looped-back puppet do a hover burst → observe. Loopback puppet via
`bridge.py` + `ghost_bot.py` replaying a `0x88b`/hover snapshot avoids needing a live friend.

## #2 goop-clearing (separate, harder)
Cosmetic particles can't clear pollution. Needs either the puppet to run real
`TWaterGun::emit` during the burst (architecture A can do this — emit real water for the few
burst frames only, cheap) OR world-sync the goop removal (protocol change). Decide after #1.
