# John → Il Piantissimo (on the working 120fps client)

You already have the 120fps client running great and the **CustomModels package**
Kris sent you. Becoming Piantissimo is three small steps — no new ISO download,
nothing to coordinate with anyone. Everything code-side is already in git.

Piantissimo's model id is `9f79b83f`. You never type the id — the launcher takes
the name `piantissimo`.

## 1. Pull the repo

```powershell
git -C C:\code\high-fps-sunshine pull
```

This brings in the skin-aware launcher (it now passes your skin to the bridge)
and `skins_install.py`. VERIFY:
`Test-Path C:\code\high-fps-sunshine\sunshine\bsmso\mac-online\skins.py` is True.

## 2. Make sure the 14 skin packs are ON YOUR DISC

You can only *be* Piantissimo (and *see* Kris as Mario / Aaron as Luigi) if your
disc carries the packs at `/data/bsmso_models/`. The mod silently falls back to
retail Mario if a pack is missing — no error.

**Quick check first — you may already have them.** In Dolphin, right-click the
BSMSO game → Properties → Filesystem → expand the disc and look for
`files/data/bsmso_models/`. If `9f79b83f.arc` and `cadf67c6.arc` (Luigi) are
there, **skip to step 3** — your disc is already baked.

**If they're missing, bake them in once** (using the CustomModels folder Kris
sent you). `skins_install.py` needs the disc *extracted* first:

```powershell
pip install pyisotools
# a) extract your ISO to the exact path the script expects:
#    In Dolphin: right-click the game -> Properties -> Filesystem ->
#    right-click the disc root -> "Extract Entire Disc..." ->
#    choose  C:\sms\bsmso-work\bsmso-root\root
#    (you should end up with ...\root\sys\main.dol and ...\root\files\)
# b) install the packs and rebuild your fork ISO in place:
python C:\code\high-fps-sunshine\sunshine\bsmso\mac-online\skins_install.py `
    --rebuild `
    --packs "<path to the CustomModels folder Kris sent>" `
    --work  C:\sms\bsmso-work
```

It bakes all 14 packs into `BSMSO-GMSE01-highfps.iso` (writes a `.new.iso` first,
renames over the original only on success). It prints
`skipping the stock BSMSO-GMSE01.iso rebuild` — that's expected; you only have
the fork disc. VERIFY: the filesystem check above now shows `9f79b83f.arc`.

> Don't want to extract/rebuild? Ask Kris for the already-baked
> `BSMSO-GMSE01-highfps.iso` and just drop it in — same result, bigger download.

## 3. Set your skin to Piantissimo

Edit `C:\code\high-fps-sunshine\sunshine\launcher\profiles.json`. In the
`"Online 120"` profile, set your name and add a `skin` line:

```json
{
  "name": "Online 120",
  "player_name": "John",
  "skin": "piantissimo",
  ...
}
```

VERIFY:
```powershell
python -c "import json;p=[x for x in json.load(open(r'C:\code\high-fps-sunshine\sunshine\launcher\profiles.json'))['profiles'] if x['name']=='Online 120'][0];print(p['player_name'],p.get('skin'))"
```
prints `John piantissimo`.

## 4. Launch

```powershell
cd C:\code\high-fps-sunshine\sunshine\launcher
python drive_launcher.py "Online 120"
```

VERIFY: the launcher log shows `Starting bridge (name=John, fps=120, skin=piantissimo)…`.
Walk into Delfino Plaza — the bridge attaches once you're in a stage
("comm buffer not found" on the title screen is normal).

## What everyone sees

- You're `piantissimo`, Kris is `mario` (retail), Aaron is `luigi`.
- Model ids are identical across every BSMSO install, so once all three discs
  carry the packs, everyone renders everyone correctly. Nobody configures
  anyone else's skin — you each set only your own.
