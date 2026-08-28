# BUG: BSMSO start menu — Start interrupts idle demos but save select unreachable

**Reported 2026-08-28 (late night) by Kris, PC, Online 120.** Status: UNDIAGNOSED,
prime suspect identified below. Written as the handoff for a fresh session.

## Symptom

On the Better Sunshine Engine Online custom start menu (BSMSO fork disc, BSE-120):
pressing Start DOES interrupt the idle attract cutscenes (so the button reaches the
menu code at least partly), but the player CANNOT proceed into save/file select.
Suspected fix conflict — this exact code set has never run together before.

## Exact machine state when reported

- PC = host, Online 120 (`drive_launcher.py "Online 120"`), EmulationSpeed 2.0,
  fork exe `dolphin-src\Binary\x64\Dolphin.exe` (v3 pacer build, 2026-08-27 18:43 —
  pacer dormant, no interp env).
- **Enabled set (20, verbatim from the launch):** $FOV 64 BSE, $Menu key-repeat
  BSE-120 v2, **$Substep 120Hz sim pin BSE-240**, $Particle parity BSE-120,
  $HUD StarFix v4 BSE-120, $Wipe pace 30Hz gate BSE-120, $SE frame-process 30Hz
  gate BSE-120, $EFB peek 30Hz gate BSE-120, $Noki pollution 30Hz gate BSE-120 v6,
  $Jump-chain window x4 BSE-120, $Anim-rate Petey vomit-window BSE-120,
  $Heat-haze shimmer pace, $Game-clock fix v15 BSE-120, $Poink premature-explosion
  gate v14 BSE-120, $Bird walk accel x2 BSE-120, $DuneBud emitter null-guard BSE,
  $Blue-coin lifetime v6-BSE, $J3D duplicate-entry guard v3, $Camera look-up
  extension v10, $FLUDD Aim Invert v3.
- Earlier tonight the SAME PC ran Online 240 (in-game fine) and John ran a working
  BSE-120 client (his set = switch_rate's, WITHOUT drive_launcher's rewrites).
  Kris got into saves fine all night at 240. This is the FIRST 120 launch on this
  PC with tonight's additions.

## PRIME SUSPECT — the substep pin enabled at 120

`$Substep 120Hz sim pin BSE-240` is a **240-only** code (fpspatch emits it only at
fps > 120), but `launcher/smslaunch/config.py` BASELINE_FIXES deliberately enables
it at 120 too, with the comment "its constants are 120Hz-sim-correct at every BSE
rate, so enabling it at 120 … is harmless-correct." **That claim was never
field-tested at 120 on the BSMSO menu — tonight's symptom is what falsifying it
would look like:**

- The pin bundles the **v9 input latch (C2 @0x802A600C), reused VERBATIM from the
  stock kit — UNGUARDED** (no BSE 2.0f/4.0f guard; safe at 240 only because the
  title is only supposed to be enabled there).
- The latch body **zeroes controller trigger edges** on frames it classifies as
  non-substep, gated by a TMarDirector **vtable check** — i.e. it was made safe for
  GAMEPLAY. The BSMSO **custom start menu** runs under a different director; how
  the latch (and the pin's zero-substep C2 @0x80299958 + granularity constants)
  interact with THAT director on the title screen was never audited. A trigger
  edge eaten at the "enter save select" transition matches the symptom exactly
  (Start reaching the demo-interrupt path but not the menu-advance path is
  consistent with partial trigger zeroing).
- Supporting history: the whole menu-director bug class (HANDOFF-INPUT-BUG.md §8:
  TSelectDir/TMenuDir tick at render rate, select_gate's three shipped-and-
  user-sighted traps) proves menu directors never behave like TMarDirector.

## Triage order (fastest first)

1. **Live A/B, 30 seconds, no relaunch:** Alt+Enter out of fullscreen → right-click
   the game → Properties → Gecko Codes → UNTICK `$Substep 120Hz sim pin BSE-240` →
   back to the start menu → try to enter save select. Dolphin applies Gecko toggles
   live. If it works: suspect confirmed → make the 120-enable conditional
   (BASELINE_FIXES pin row must check `fps > 120`, or the pin needs a BSE-240
   guard on the latch block). If not: retick it (it IS needed at 240) and continue.
2. Next suspects in order: `$Menu key-repeat BSE-120 v2` (menus, but John's
   working client had it — weak suspect), `$FOV 64 BSE` (newly resolved this
   launch; mProjectionFovy poke should be visual-only), then binary-search the
   remaining 120-guarded codes by live untick (they're all live-toggleable).
3. Distinguish "can't SELECT" from "can't SEE": if save select opens but input is
   dead inside it, that's the menu-director input class (§8); if the menu never
   transitions, it's a state-machine/trigger issue (latch class).
4. When root-caused: fix in fpspatch/config (guard or rate-scope), `--check`
   enforce, push, and update the client kit — `sms-120-perfect-kit.zip` on the
   OneDrive Desktop contains a **config snapshot with this bug's enabled set** —
   REGENERATE the snapshot (copy the fixed live INIs into the package
   `config-templates\` and re-zip) before anyone else deploys it.

## Context every next session needs (the night in one paragraph)

Online is LIVE: PC hosts BSMSO server on `192.168.4.58:27015` (TCP+UDP, firewall
rules BSMSO-27015-*; **the PC's LAN IP changed from 192.168.1.20 — old docs lie**),
Mac joined at 120, John joined remotely at 120 (Radmin planned; he's been
connecting fine). Tonight's shipped work, newest first: Petey anim-rate split out
of the quarantined family (5405f07), jump-chain window x4 — triple jump fix from
John's field A/B (231e53f, HANDOFF-JUMPCHAIN-BUG.md), verification-driven client
guide SETUP-CLIENT-120.md + iso_for fallback (403b18a), Noki v6 enabled online
(+35-50fps Bianco, a5d6de2), J3D-guard launcher regex bug fixed — unanchored
regex matched the Noki title and enabled the WRONG code (cfd7933), EFB peek gate
ported to BSE (f68f1ab). Distribution: `sms-120-perfect-kit.zip` (1.05GB, OneDrive
Desktop) = ISO + fork Dolphin + repo archive + config snapshots + README-AI.md
(which carries the complete fix audit: shipped / quarantined-why / not-needed-at-
120 / unported-why). NEEDS-TEST still open: Petey boss, triple-jump feel, select-
menu gate at 240, turnaround-skid feel under BSE — and now THIS bug.

## House rules (paid for in blood — do not re-learn)

- Dolphin rewrites `GMSE01.ini` from memory on quit: NEVER edit INIs while it
  runs; use the launcher/switch_rate flow or the dolphin-gecko skill.
- NEVER send keys/UAC prompts while Kris is playing (game_io pause incident).
- Dolphin in-game ignores CloseMainWindow — ask Kris to close, arm a
  Wait-Process watcher for the relaunch (pattern used all night).
- Verify hooks in MEMORY, not just the INI: `bsmso/mac-online/peekcheck.py`, or
  `DolphinMem(find_dolphin_pid())` → `locate_comm_buffer()` (in a stage) →
  `.read()`. Title-screen MEM1 reads: comm buffer does NOT exist there.
- Exactly ONE fps bundle/rate enabled at a time; only switch via switch_rate/
  launcher. Unverified ports stay UNVERIFIED-marked and unticked until an
  in-game pass.
- git: pull --rebase before push (Mac + other sessions share the branch); no
  double-quote characters inside PowerShell-heredoc commit messages.
