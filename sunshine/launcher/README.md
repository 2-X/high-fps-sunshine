# SMS high-FPS launcher (Textual TUI)

One screen to configure and launch Super Mario Sunshine at high FPS, online or
offline, with a chosen FPS, FOV, and set of QOL fixes, saved as named profiles.

```
sunshine/launcher/sms          # run it (bootstraps its own venv on first run)
```

## First-run setup (do this once)

```
cd sunshine/launcher
./sms setup
```

The setup wizard gets a newcomer from a freshly-cloned repo to a working 120fps
build with near-zero manual steps: it records your dumped disc, downloads the
**prebuilt patched Dolphin** (macOS arm64) and de-quarantines it (the app is
unsigned), installs the Dolphin config kit, **guarantees the MEM1 override**
(`RAMOverrideEnable` / `MEM1Size`; without it the FOV/widescreen Gecko codes
silently never run), sets your player name, and optionally installs the UHD
texture pack.

It is **idempotent and safe to re-run**: anything already configured reports
`[already OK]` and is untouched, and any file it would overwrite is copied into a
timestamped `sms-setup-backup-<ts>/` under your Dolphin user dir first. Plain
`./sms` also offers to run the wizard if the ISO or Dolphin build is missing.

Prefer to build Dolphin yourself? Choose option **[2]** (point at an existing
build) or **[3]** (build-from-source instructions) in the wizard's Dolphin step;
see [../dolphin-patches/README.md](../dolphin-patches/README.md).

## Setup on your machine

### Requirements

- **macOS** (Mac-only; no Windows support).
- **Python 3.10+**: the `sms` script checks and prints a clear error if older.
  Install with `brew install python@3.12` if needed.
- **Textual 8.2.8**: pinned in `requirements.txt`; installed automatically into
  `.venv/` on first run of `sms`.

### Path configuration

The launcher ships with hardcoded default paths that match the original developer
machine. On a different machine, override just the paths that differ, without
touching this file.

**Option 1: `config.local.json`** (recommended; gitignored):

```
cp sunshine/launcher/config.local.json.example sunshine/launcher/config.local.json
```

Then edit the copy:

```json
{
  "iso_offline":  "/path/to/Super Mario Sunshine (USA).rvz",
  "iso_dir":      "/path/to/bsmso-work",
  "dolphin_app":  "/path/to/repo/dolphin/build/Binaries/Dolphin.app",
  "dolphin_user": "~/Library/Application Support/Dolphin"
}
```

All keys are optional; only override what differs from the defaults.

**Option 2: environment variables** (highest priority; useful for CI / wrappers):

| Variable            | What it overrides        |
|---------------------|--------------------------|
| `SMS_ISO_OFFLINE`   | Path to the SMS .rvz/.iso |
| `SMS_ISO_DIR`       | Directory with BSE ISOs   |
| `SMS_DOLPHIN_APP`   | Path to Dolphin.app       |
| `SMS_DOLPHIN_USER`  | Dolphin user-data folder  |

Precedence: **env var > config.local.json > built-in default**.

If `ISO_OFFLINE` doesn't exist at startup the launcher prints an actionable error
naming these two options and exits. No cryptic crash.

### Profiles customization

`profiles.json` is tracked in git with generic placeholder names (`player_name:
"Player"`). To keep your personal profiles without dirtying git:

1. Copy `profiles.json` to `profiles.local.json` (gitignored).
2. Edit `profiles.local.json` freely: set your name, tweak defaults, add
   profiles. The launcher auto-detects and loads it in place of `profiles.json`.
3. Saves and edits from the TUI write back to whichever file was loaded.

## What it does

- **Profiles** - save / load / edit / duplicate / delete named setups. The last
  one you launched is remembered and reselected next time. Stored in
  `profiles.json` (+ `last`), right next to the app.
- **Online / Offline** - one selector; it picks the disc *and* the code set:
  - **Offline** → the plain **Super Mario Sunshine (USA).rvz** disc + our stock
    high-fps Gecko kit. **Any FPS** (multiple of 60 ≥ 120): the launcher runs
    fpspatch to build the bundle. Solo, no server.
  - **Online** → the **BSMSO / Better Sunshine Engine** disc. FPS is a *native*
    BSE setting (30 / 60 / 120, or 240 / 280 / 320 on the `-highfps` fork disc),
    snapped to the nearest. Adds the server + bridge (+ optional ghost bot).
- **Aspect / widescreen** - the Aspect dropdown (16:9 / 16:10 / **4:3 no
  widescreen**) is the whole widescreen control. Offline it enables the matching
  projection Gecko (`$Widescreen` for 16:9, a generated `$Widescreen 16:10` for
  16:10) **plus the level-entry curtain/wipe fix**; **4:3 applies no widescreen
  code at all** (native pillarboxed). Online it sets BSE's native aspect. It also
  sets Dolphin's display aspect. No separate widescreen toggle.
- **FOV** - type the **horizontal** FOV (the normal game number, ~70–120) and the
  launcher converts it to the vertical fovy the `$FOV` Gecko sets (per aspect) and
  reuses/builds that code. **Leave it blank to apply no FOV code at all**: the
  game keeps its stock FOV.
- **QOL toggles** - only genuine preference codes: Camera look-up, FLUDD aim
  invert, Save-box Continue-on-top, Tank controls. The framerate *correctness*
  fixes are **auto-applied**, not toggles: offline they're baked into the fpspatch
  bundle; online they're the BSE baseline set (particle parity, SE/wipe/anim-rate
  pacing, blue-coin timer, …) enabled for you.
- **HD textures** - a tri-state selector (works in both modes): **"off"** disables
  hires textures for SMS (files stay on disk); **"portals"** installs the pruned
  UHD pack (226MB: Delfino M-portal textures + FLUDD/lives/coins HUD, digits,
  shine icons, episode-select wordmarks) into Dolphin's `Load/Textures/GMSE01/`
  as a symlink and enables `HiresTextures`/`CacheHiresTextures` for SMS; **"full"**
  installs the full qashto/razius "SMS 4K 2.0c" pack to `Load/Textures/GMS/`,
  auto-extracting from `sunshine/textures/SMS 4K*.zip` on first use (~770MB),
  and removes the `GMSE01` symlink (which would shadow the GMS folder). On a fresh
  machine, place the full-pack zip in `sunshine/textures/` before launching in
  "full" mode; if missing, the launcher prints an error with the expected filename.
  Both discs are GMSE01, so "portals" applies offline and online alike.
- **Generate-if-missing, reuse-if-present** - for the offline FPS bundle and the
  FOV code. The preview shows which already exist and which will be built.

## The launch flow (what "Apply & Launch" runs)

1. Quit Dolphin (so it can't rewrite `GMSE01.ini` on exit).
2. Generate the FOV code if this angle was never built, and add it to `[Gecko]`.
3. Set the **exact** `[Gecko_Enabled]` list: FOV + the always-on baseline fixes +
   whichever QOL toggles are on (nothing stale left enabled).
4. Set `[Core]` `EnableCheats=True`, `EmulationSpeed=FPS/60`, `AudioPreservePitch`.
5. Set the display aspect (`[Video_Settings]`), and MEM1=64MB (BSE puppet heap).
6. Set the display aspect + (if **HD portals** on) install the pruned pack to
   `Load/Textures/GMSE01/` and set `HiresTextures`/`CacheHiresTextures` in
   `[Video_Settings]` (`hdtextures.apply`).
7. Boot the right ISO; then poke the native FPS/aspect. Offline: `set_bse_fps.py`;
   online: server + `bridge.py` (+ ghost), which re-assert it every loop.

## Keys

`Ctrl+S` save · `Ctrl+L` apply & launch · `Ctrl+R` refresh preview · `Ctrl+Q` quit.

## Layout

- `smslaunch/config.py`   - paths, ISO/FPS/aspect maps, the QOL catalog.
- `smslaunch/codegen.py`  - fpspatch FPS bundle + templated `$FOV N` generator.
- `smslaunch/inieditor.py` - safe GMSE01.ini editing (Dolphin-quit guard + backup).
- `smslaunch/launcher.py` - `apply()` + `launch()` orchestration, read-only `plan()`.
- `smslaunch/profiles.py` - profile schema + JSON store + last-used.
- `smslaunch/app.py`      - the Textual UI.

## Notes / limits

- Offline FPS: any multiple of 60, floor 60 (60 = native, no bundle; ≥120 builds
  the fpspatch bundle; no upper limit). Online FPS: the BSE native set
  (30/60/120/240/280/320); 240+ needs `BSMSO-GMSE01-highfps.iso`. Type freely;
  the field doesn't snap while you type; the preview shows the effective value.
- FOV input is **horizontal** degrees; the code sets the matching vertical fovy
  for your aspect (so the same number gives the same feel on 16:9 vs 16:10).
- Both discs are GMSE01, so they share one `GMSE01.ini`; the launcher rewrites
  the exact `[Gecko_Enabled]` set on each launch so the two never cross-contaminate
  (no fpspatch bundle under BSE, no BSE codes on the stock disc).
- Every INI mutation backs up to `GMSE01.ini.bak` first and refuses to run while
  Dolphin is alive.
