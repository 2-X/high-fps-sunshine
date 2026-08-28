# BSMSO character skins — Luigi, Wario, Yoshi & co.

Updated 2026-08-28. Pickup doc for other players (PC/Windows especially) plus
the Mac wiring notes. TL;DR: the online mod has always had skins; our kit now
uses them.

## What exists

BSMSO 1.1 ships 14 character packs in `CustomModels/` (in the mod zip, and
locally at `upstream/BSMSO_1.1/CustomModels/`): **Luigi**, Shadow Luigi,
Shadow Mario, Shadow, Wario, Waluigi, Yoshi, Birdo, Sonic, Piantissimo,
Needle, Nokissia, Daytendo, Nightendo.

Mechanism (verified against the decompiled launcher/server code and the
`_BSMSO.kxe` strings — details in `mac-online/skins.py`):

- Each pack has an 8-hex **model id** (`CustomModels/library.json`;
  Luigi = `cadf67c6`). The game loads the pack **from the disc** at
  `/data/bsmso_models/<id>.arc`. Missing pack → silent retail-Mario fallback.
- Your selection is written to the shared comm block (`LocalMarioModelId`
  @1297) and sent with the join; live changes broadcast to the session via
  `MarioModelIntent`. Remote players' ids arrive in the roster and get
  mirrored to `RemoteMarioModelIds` @1305.
- **You only see a peer's skin if your own disc has that pack.** Ids are
  content-derived and identical across every BSMSO 1.1 install, so as long as
  everyone's disc/game folder carries the stock 14 packs, everyone sees
  everyone. No pack → that player renders as retail Mario for you.

## Windows players (e.g. the official-launcher setup)

Nothing from this repo is required. `BSMSO.Launcher.exe` syncs the
`CustomModels/` packs into the game folder automatically and has a **"Mario
model" dropdown** — pick Luigi there. Done.

If instead you boot a **prebuilt ISO** the way the Mac does (no launcher),
install the packs into the extracted root and rebuild:

```
pip install pyisotools
python sunshine/bsmso/mac-online/skins_install.py --rebuild \
    --packs <path-to>/BSMSO_1.1/CustomModels --work <path-to>/bsmso-work
```

## Mac (this machine)

Done 2026-08-28: both ISOs (`BSMSO-GMSE01.iso`, `-highfps.iso`) rebuilt with
all 14 packs baked in (`skins_install.py --rebuild`; it swaps the stock
v4.0.0 kxe in for the stock-ISO build and restores the fork kxe after).

Pick a skin in the `sms` launcher (**Skin** row, online mode) or directly:

```
python bridge.py --server <host> --name Kris --skin luigi
```

`--skin` takes any pack name or a raw 8-hex id; typos fail the launch loudly.
The bridge writes your id at join, re-asserts it after comm-buffer relocation
(stage reload), and dirty-diff-mirrors the roster's ids for remote puppets.

Limits / untested:

- **Solo mode has no skin yet** — the bridge is what writes the comm field,
  and solo runs without one. A standalone poke (set_bse_fps.py-style) would
  work IF the kxe polls `LocalMarioModelId` outside a session — untested.
- First in-game eye test pending (puppet skin + local skin at 120 online).

## "Do our fixes help Windows, or are they Mac-specific?"

Most of the good stuff is **platform-independent**, because it patches the
*game*, not the emulator. Rule of thumb: if `fpspatch.py` generates it, it
works identically on any platform's Dolphin.

Portable (Gecko/C2 codes from `fpspatch.py` — regenerate per FPS, never
hand-copy; see the fpspatch memory/README):

- Game-clock/timer fix v15, blue-coin timer v6, Petey vomit v16, Poink v14,
  HUD-star StarFix v4, repeating-SE 30Hz gate, Noki pollution v6,
  J3D duplicate-entry guard v3 (the Bianco freeze fix — both discs),
  EFB peek gate, jump-chain v2, boid/fish gate (offline + the new BSE port
  in this commit), widescreen 2D fix v2, 16:10 world aspect, save-box
  Continue-on-top, pause-while-jumping, music DSP-limiter fix, FOV.

Already on Windows / originated there:

- Non-blocking EFB readbacks (`HiFpsNonBlockingReadbacks`) — PC build had it
  first; it's the thing the *Mac* build lacks.
- Async shader compilation kit (mode 3 + warmed cache) — ported PC-ward in
  commit 35df539 after the Mac Bianco-stutter finding.

Genuinely Mac-specific (ignore on Windows): loose-SyncGPU ARM default,
codesign/entitlement dance, Quartz input INI dialect, memhelper, Metal
draw-wall findings.
