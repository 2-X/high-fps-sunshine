# Windows: moving from 60 → 120 fps online (BSMSO)

Updated 2026-08-28. For the Windows player still on 60: 120 is a **native BSE
rate** — no fork disc needed (the fork kxe only adds 240/280/320) — and
sessions are position-synced, not lockstep, so you can run 120 while others
run 60 or 240. Nothing to coordinate.

## The one command

Pull this repo (`main`), close Dolphin, then:

```powershell
powershell sunshine\bsmso\mac-online\play240.ps1 -Fps 120
```

That script is the Windows launcher and does the whole rate change in the
order that works (see its header comments): regenerates the **BSE-120
companion bundle fresh from `fpspatch.py --bse`** (never reuse a stored
bundle — stale bundles fail silently), installs the static codes (menu
key-repeat v2, DuneBud null-guard), the boot-time `04` force-writes (BSE
cold-boots at 30fps/4:3 every launch), sets `EmulationSpeed = 2.0` in both
INIs, boots, and then **proves** the codes installed by attaching to live
memory.

If you'd rather keep your own launch flow, the config half alone is:

```powershell
python sunshine\bsmso\mac-online\switch_rate.py --fps 120
```

## Check the verify log — always

`%TEMP%\sms-verify.log` names every enabled code that did NOT actually
install. A silently-dead code list looks identical to a working one in the
Dolphin UI (and Dolphin never enables `$Title [creator]`-style bracket
titles — the kit writes stripped names for this reason). If something feels
off at 120, read this log before debugging anything else.

## What 120 fixes vs what it breaks (all handled)

At 120 the game logic runs 2x, which historically broke timers, blue coins,
Petey's fight, HUD stars, repeating sound effects, fish schools, music, and
more. Every one of those has a fix in the companion bundle the launcher
generates — that's the point of regenerating from `fpspatch.py` rather than
enabling codes by hand. Don't cherry-pick; take the bundle.

## If 120 doesn't hold (perf ideas, in order of payoff)

1. **Async shader compilation + warmed cache** — the cold-cache stutter fix
   (commit 35df539): `ShaderCompilationMode = 3` in the per-game INI, and
   play ~90 seconds for the cache to warm before judging stutter.
2. **Backend**: Vulkan beat OpenGL by a wide margin in our measurements
   (Bianco ~170 → ~315 VPS class gains with the peek gate).
3. **EFB peek gate** is already in the BSE-120 bundle (Mario-occlusion +
   sun-flare peeks are synchronous pipeline stalls at render rate) — another
   reason not to hand-trim the bundle.
4. **If hosting the server on the same PC**: `SMSO.ServerHost` busy-waits a
   full core and starves Dolphin. Set it Below Normal in Task Manager (the
   Mac launcher does the equivalent renice automatically).
5. **HD texture packs off** while chasing a stable 120; re-enable after.

## Audio and the custom Dolphin build

Correct 120 audio (tempo AND pitch) needs the kit's patched Dolphin build,
not stock: the binary DMA tempo patch + `AudioPreservePitch = True`. The kit
build also carries the Gecko capacity lift (stock Dolphin silently stops
running late-list codes when the region fills — the 120 bundle is big) and
non-blocking EFB readbacks. If you're on stock Dolphin and audio sounds
chipmunked or slow, that's why.

## Skins

Unrelated to fps but landed at the same time: see `SKINS.md`. Official-
launcher installs already have the "Mario model" dropdown (pick Luigi);
prebuilt-ISO setups run `skins_install.py --rebuild`. Everyone's skin shows
for everyone who has the packs on their own disc.
