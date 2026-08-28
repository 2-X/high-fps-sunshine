#!/usr/bin/env python3
"""fpspatch.py — generate the Super Mario Sunshine (GMSE01) high-FPS Gecko bundle
for ANY target framerate.

Set G = FPS/60. Retargeting rescales FOUR independent things, and an earlier
version of this docstring was wrong to claim it was only the framerate word —
that assumption is exactly how the fixed 1-in-2 particle gate shipped at 180fps:

  1. the "framerate global" at 0x804167B8  →  float(G), plus EmulationSpeed = G
  2. the emitter gate                      →  1 substep in G      (_rate_gate)
  3. substep granularity                   →  stock 600/5 scaled by G
  4. the Noki pollution gate               →  1 frame in FPS/30 (= 2G, not G)
  5. the shine-select screen gate         →  1 frame in ceil(G/2) (select_gate)
  6. the Hx wipe clock                     →  1 frame in FPS/30 (wipe_pace) —
     every wipe (incl. the level-entry decompose/recompose) is frame-counted
     for 30fps rendering and otherwise plays 2G x too fast
  7. the audio pump MSound::mainLoop       →  1 frame in FPS/30 (audio_pump_gate)
     — SE request processing must never outrun the 120 Hz substep request rate
     or continuous SEs flicker-restart and thrash the 64-voice pool (the 240fps
     total-music-silence bug)
  8. the THP movie clock                   →  divisor 5994*G (thp_pace) — the
     SDK THPPlayer paces off VI retraces, which fire G x wall speed under
     EmulationSpeed=G, so silent movies (the M-portal previews) play G x fast;
     audio-mastered cutscene THPs are excluded via the audioExist discriminator
     to keep their A/V sync
  9. the Ricco hook slide-clank            →  1 frame in FPS/30
     (riccohook_se_gate) — keyed on the audio pump's frame counter, because
     the pump gate alone measurably does not tame this per-tick SE flood (the
     240fps "womp womp womp" near the gondola)
  10. the SE frame-process gate (hover/creak/tentacle cadence) → 1 frame in
      FPS/30 rendered frames (se_frame_gate), exactly like the Noki gate —
      supersedes the old per-site cogwheel request gate, which starved the
      keep-alive window and chopped every repeating SE at 2x native rate
  11. the boid flocking update TBoidLeader::perform → 1 tick in 2, CONSTANT
      (boid_gate) — fish schools (and the Gelato red coin towed by one) and
      butterflies take a fixed-size step per CALC_ANIM cue with no delta-time;
      the cue is ~120 Hz pinned at every G and the native rate is 60 Hz, so
      this is the JPA particle-parity cadence (substep-counter parity), NOT
      an FPS/30 divisor — the v1 FPS/30 form played the school 2x slow

Rate-INDEPENDENT, and correct as-is at every G:
  * hooks that READ the framerate global and self-scale — the raw anim-rate
    x0.25 fixes (constant, because calc_anim is pinned at 120 Hz by the substep
    retune — an earlier /(2G) form was wrong at G>=3), the animal movement-rate
    x4 restores (substep-paced speeds, see ANIMAL_SPEED_SITES), and the
    game-clock fix (v15), which divides OSCheckStopwatch
    ticks by G (shift for powers of two, long division for 180)
  * M-portal glow (XZ-distance reimpl) and ForceOpen (calls the real startOpen)
  * BGM DSP voice-limiter kill + tempo guard; the HUD stars fix
  * the Poink gate — its bare `cmpwi 40` looks rate-tied but flyTimer runs on
    substep-invariant spine ticks, so 40 keeps its stock meaning at every G
  * the skid-turn freshness fix — its bare 4-tick face delay is the stock 30 Hz
    pad staleness expressed in 120 Hz sim ticks, constant at every G (same
    reasoning again); it self-gates on the framerate global != 0.5f

Deliberately NOT generalized: the blue-coin lifetime fix, calibrated against this
machine's measured substep rate rather than derived from G, so it is emitted only
at 120fps.

Usage:
  fpspatch.py 120                  # print the 120fps bundle + EmulationSpeed
  fpspatch.py 180 -o out.txt       # write the 180fps bundle to a file
  fpspatch.py 240 --no-forceopen   # v3-style: respect story locks (no ForceOpen)
  fpspatch.py 180 --check          # validate structure, decoding and constants
  fpspatch.py 180 --emit-ini       # full GMSE01.ini fragment, ready to merge
  fpspatch.py 180 --bare -o c.txt  # hex only, for gecko.py add --code-file
  fpspatch.py 240 --bse            # BSE companion bundle (120 or 240 only;
                                   #   see bse_supported() for why not 280/320)
"""
import argparse, struct, sys

# ---- FPS-INDEPENDENT building blocks (verified from the shipping TRUE-FIX v2) ----

def base(fr_word):
    # 044167B8 = the framerate global = float(FPS/60); the C20066EC effect-loop
    # hook reads it, so the whole base auto-scales off this one word.
    return f"""044167B8 {fr_word}
042FCB24 60000000
C20066EC 00000002
C2C28028 EC2105B2
FEC00890 00000000"""

# ---- particle calc parity gate (CONSTANT 1-in-2 — substep-pinned) -----------
# EmitterViewObj.cpp: perform() runs `for(i=SMSGetAnmFrameRate(); i>0; --i)
# emitter->calc()` on CUE_CALC_ANIM. SMSGetAnmFrameRate() is stubbed to 0.5, so
# fctiwz truncates to 0 calcs; injecting +1.0 on gated ticks is what advances
# the whole JPA world.
#
# THE CADENCE (three doc reversals — this one carries the evidence, do not
# flip it again without NEW evidence):
#   CUE_CALC_ANIM fires on the LAST SUBSTEP of each rendered frame — 30 Hz
#   stock, ~120 Hz under the substep retune AT EVERY G (HANDOFF-POINK §1,
#   EmitterViewObj.cpp decomp). It is NOT render-rate. The gate counts
#   gpMarDirector+0x5C, which increments once per substep — 1:1 with
#   CALC_ANIM ticks at G>=2. Native JPA rate is 60 Hz (stock: 30 Hz perform
#   x AnmFrameRate 2.0). Therefore the divisor is the CONSTANT 2:
#   120/2 = 60 Hz at every G — same substep-pinned-constant class as the
#   cogwheel 1-in-4 and the Poink 40.
#
# History: the original hand-written 120fps block hardcoded `andi. r0,r3,1`
# (1-in-2) — CORRECT. A later docstring "generalized" it to 1-in-G on the
# theory that the hook runs at render rate (60G Hz); it does not, and the
# result ran ALL JPA effects at 120/G Hz: fine at 120, 1.5x slow at 180,
# 2x slow at 240, 3x slow at 360 — user-sighted as Mario's M-portal
# atom-decompose/recompose playing at half speed at 240 (2026-08-11), and
# as the 360 recompose outliving Mario's spawn (2026-08-10). The 1-in-G
# masks ALSO explain the dots-vs-ripples desync: JPA (slowed) drifted
# against the substep-clocked warp status machine (never slowed).
#
# _rate_gate is retained as the general helper for gates whose hook cadence
# REALLY scales with G (render-rate classes like the Noki counting or the
# wipe clock):
#   * N a power of two -> `andi. r0,ctr,N-1`
#   * otherwise        -> ctr - (ctr/N)*N, an exact modulo (no mask does mod 3)

def _li(rD, imm):        return (14 << 26) | (rD << 21) | (imm & 0xFFFF)
def _andi_(rA, rS, imm): return (28 << 26) | (rS << 21) | (rA << 16) | (imm & 0xFFFF)
def _divwu(rD, rA, rB):  return (31 << 26) | (rD << 21) | (rA << 16) | (rB << 11) | (459 << 1)
def _mullw(rD, rA, rB):  return (31 << 26) | (rD << 21) | (rA << 16) | (rB << 11) | (235 << 1)
def _subf_(rD, rA, rB):  return (31 << 26) | (rD << 21) | (rA << 16) | (rB << 11) | (40 << 1) | 1

def _rate_gate(g, ctr=3, tmp=0, tmp2=4):
    """Instructions setting CR0 from (ctr mod g); a following `bne` skips the work.
    `ctr` holds the substep counter on entry and is preserved."""
    if g & (g - 1) == 0:                       # power of two -> single mask
        return [_andi_(tmp, ctr, g - 1)]
    return [_li(tmp2, g),                      # li    r4,G
            _divwu(tmp, ctr, tmp2),            # divwu r0,r3,r4   q = ctr/G
            _mullw(tmp, tmp, tmp2),            # mullw r0,r0,r4   q*G
            _subf_(tmp, tmp, ctr)]             # subf. r0,r0,r3   ctr - q*G = ctr%G

LWZ_DIRECTOR = 0x806D9FB8   # lwz   r3,-0x6048(r13)   gpMarDirector
CMPLWI_R3_0  = 0x28030000   # cmplwi r3,0
LWZ_UNK5C    = 0x8063005C   # lwz   r3,0x5C(r3)       substep counter
LFS_ONE      = 0xC002DD68   # lfs   f0,-0x2298(r2)    1.0f
FADDS_F1_F0  = 0xEC21002A   # fadds f1,f1,f0
FCTIWZ_F0_F1 = 0xFC00081E   # the overwritten original instruction
NOP          = 0x60000000

def _parity_block(hook, g):
    gate = _rate_gate(g)
    # layout: [dir load, cmplwi, beq->ADD] [unk5C load, gate..., bne->SKIP] [ADD] [SKIP]
    words = ([LWZ_DIRECTOR, CMPLWI_R3_0, 0] + [LWZ_UNK5C] + gate + [0]
             + [LFS_ONE, FADDS_F1_F0] + [FCTIWZ_F0_F1])
    i_beq, i_bne = 2, 4 + len(gate)
    i_add = i_bne + 1                          # null director falls here: do the add
    i_skip = i_add + 2
    words[i_beq] = 0x41820000 | (((i_add - i_beq) * 4) & 0xFFFC)   # beq -> ADD
    words[i_bne] = 0x40820000 | (((i_skip - i_bne) * 4) & 0xFFFC)  # bne -> SKIP
    words += [NOP, NOP]                        # preserve the proven 120fps cave layout
    if len(words) % 2 == 0:
        words.append(NOP)                      # keep the branch-back on its own slot
    words.append(0x00000000)                   # handler clobbers the last word
    out = [f"{hook} {len(words) // 2:08X}"]
    for i in range(0, len(words), 2):
        out.append(f"{words[i]:08X} {words[i + 1]:08X}")
    return "\n".join(out)

def particles(g):
    # g is IGNORED by design: CALC_ANIM ticks at ~120 Hz at every G, so the
    # 60 Hz JPA parity is the CONSTANT 2 (see the cadence block above).
    return "\n".join(_parity_block(h, 2) for h in ("C22887A8", "C2288D30", "C2288DEC"))

FORCEOPEN = """C21EB034 00000007
88030070 700B0001
40820020 7D6802A6
3D80801E 618CBFD4
7D8903A6 4E800421
7D6803A6 7FE3FB78
88030070 60000000
60000000 00000000"""

# ---- Game-clock fix (v15): race/countdown timers ----------------------------
# SMS clocks (blooper race, Piantissimo, time-limit countdowns, verdict times)
# are OS-tick STOPWATCH based, not frame counters: every one reads the director
# event stopwatch (gpMarDirector+0xE8) through OSCheckStopwatch @0x80348114
# (exactly 4 callers, all this stopwatch). The emulated timebase advances
# EmulationSpeed-times real time, so clocks run G=FPS/60 times too fast.
# Fix: hook the single exit (blr @0x80348180, r3:r4 = total ticks) and divide
# the 64-bit tick count by G, gated on the framerate global containing exactly
# float(G) (stock 0.5f -> gate fails -> no-op without the fps code).

def _rlwinm(a, s, sh, mb, me):
    return 21 << 26 | s << 21 | a << 16 | sh << 11 | mb << 6 | me << 1

def _rlwimi(a, s, sh, mb, me):
    return 20 << 26 | s << 21 | a << 16 | sh << 11 | mb << 6 | me << 1

def timerfix(fps):
    """C2 block scaling OSCheckStopwatch's 64-bit tick result by 60/fps.
    Returns None when fps/60 is not an integer > 1 (no exact fix)."""
    g = fps / 60.0
    if g <= 1 or g != int(g):
        return None
    g = int(g)
    gate = struct.unpack(">I", struct.pack(">f", float(g)))[0]
    words = [0x3CA08041, 0x80A567B8]                 # lis r5,0x8041; lwz r5,0x67B8(r5)
    words.append(0x3CC00000 | (gate >> 16))          # lis r6,hi16(float G)
    if gate & 0xFFFF:
        words.append(0x60C60000 | (gate & 0xFFFF))   # ori r6,r6,lo16
    words.append(0x7C053000)                         # cmpw r5,r6
    if g & (g - 1) == 0:                             # power of two: 64-bit >> sh
        sh = g.bit_length() - 1
        body = [
            _rlwinm(4, 4, 32 - sh, sh, 31),          # srwi r4,r4,sh
            _rlwimi(4, 3, 32 - sh, 0, sh - 1),       # lo top bits <- hi low bits
            _rlwinm(3, 3, 32 - sh, sh, 31),          # srwi r3,r3,sh
        ]
    else:                                            # base-2^16 long division by g
        body = [
            0x38C00000 | g,                          # li    r6,g
            0x7CE33396,                              # divwu r7,r3,r6   q_hi
            0x7D0731D6,                              # mullw r8,r7,r6
            0x7D081850,                              # subf  r8,r8,r3   rem
            0x7CE33B78,                              # mr    r3,r7
            _rlwinm(7, 4, 16, 16, 31),               # r7 = lo>>16
            _rlwimi(7, 8, 16, 0, 15),                # r7 |= rem<<16
            0x7D073396,                              # divwu r8,r7,r6   q1
            0x7CA831D6,                              # mullw r5,r8,r6
            0x7CA53850,                              # subf  r5,r5,r7   rem2
            _rlwinm(7, 4, 0, 16, 31),                # r7 = lo & 0xFFFF
            _rlwimi(7, 5, 16, 0, 15),                # r7 |= rem2<<16
            0x7CA73396,                              # divwu r5,r7,r6   q0
            0x38850000,                              # addi  r4,r5,0
            _rlwimi(4, 8, 16, 0, 15),                # r4 |= q1<<16
        ]
    words.append(0x40820000 | (len(body) + 1) * 4)   # bne -> blr
    words += body
    words.append(0x4E800020)                         # blr (replaces original)
    if len(words) % 2 == 0:
        words.append(0x60000000)                     # keep pad on its own slot
    words.append(0x00000000)                         # handler clobbers last word
    lines = [f"C2348180 {len(words) // 2:08X}"]
    for i in range(0, len(words), 2):
        lines.append(f"{words[i]:08X} {words[i + 1]:08X}")
    return "\n".join(lines)


def _c2(addr, words):
    """Format a C2 block: pad so the handler-clobbered 00000000 lands last."""
    words = list(words)
    if len(words) % 2 == 0:
        words.append(NOP)                      # keep the branch-back on its own slot
    words.append(0x00000000)
    out = [f"C2{addr & 0x01FFFFFF:06X} {len(words) // 2:08X}"]
    for i in range(0, len(words), 2):
        out.append(f"{words[i]:08X} {words[i + 1]:08X}")
    return "\n".join(out)


# ---- Substep granularity (the 180fps v8 lineage) ----------------------------
# TMarDirector's substep scheduler runs a fixed-point accumulator whose stock
# constants are 600 and 5 (verified against research/main.dol):
#   0x8029985C  li    r3,600        38600258
#   0x80299974  addi  r0,r3,-5      3803FFFB
#   0x80299980  cmpwi r0,5          2C000005
# Scaling both by G subdivides each native tick into G substeps, which is what
# makes the sim advance smoothly at G x 60 Hz instead of taking one giant step
# per frame. The shipping "$180fps v8" bundle used 1800/-15/15 — exactly stock*G
# at G=3 — so the rule is simply stock*G, with no other constant involved.
# The C2 @0x80299958 carries the same 5*G threshold and skips the substep when
# the accumulator has not yet earned one.

def substep_granularity(g):
    tick, thresh = 600 * g, 5 * g
    words = [0x801A0054,                       # lwz   r0,0x54(r26)   accumulator
             0x2C000000 | thresh,              # cmpwi r0,5G
             0x40800024,                       # bge   -> original insn (skip 9)
             0xA01A004C,                       # lhz   r0,0x4C(r26)
             0x60004000,                       # ori   r0,r0,0x4000   zero-substep flag
             0xB01A004C,                       # sth   r0,0x4C(r26)
             0x3BA00000,                       # li    r29,0
             0x3D808029, 0x618C9C00,           # lis/ori r12,0x80299C00
             0x7D8903A6, 0x4E800420,           # mtctr r12 ; bctr  -> epilogue
             0x3B9C0001]                       # addi  r28,r28,1     (original insn)
    return "\n".join([
        f"0429985C {0x38600000 | tick:08X}",           # li    r3,600G
        f"04299974 {0x38030000 | (-thresh & 0xFFFF):08X}",  # addi  r0,r3,-5G
        f"04299980 {0x2C000000 | thresh:08X}",         # cmpwi r0,5G
        _c2(0x80299958, words),
    ])


# ---- SMSGetAnmFrameRate stub (v11) ------------------------------------------
# 0x802A7BD8 is SMSGetAnmFrameRate() = 60.0f / SMSGetVSyncTimesPerSec(), i.e.
# 60/(60*G) = 1/G, with 215 callers. Stubbing its prologue to `lfs f1,-0x7FD8(r2)
# ; blr` makes it return a hard 0.5f.
#
# That is correct BECAUSE substep_granularity pins the sim: with numerator 600G
# and quantum 5G, each direct() adds 600G/(60G) = 10 (always an exact divide) and
# each substep costs 5G, so the sim runs 60G * 10/(5G) = 120 Hz at EVERY G. The
# right return is therefore 60/120 = 0.5 regardless of framerate, whereas the
# stock formula would give 1/G and run anims 1.5x slow at 180fps.
#
# So it is a no-op at G=2 (1/G is already 0.5) and a real fix at G>=3 — which is
# why v11 introduced it for the 180fps line. It is only valid alongside the
# substep retune, hence build() ties it to `substep`.
ANMRATE_STUB = """042A7BD8 C0228028
042A7BDC 4E800020"""

# ---- Input latch (v9) -------------------------------------------------------
# TApplication::gameLoop @0x802A5F50 calls TMarioGamePad::read() @0x802A8054
# once per DISPLAYED frame, so at high FPS a press/release edge is reported
# several times per sim step. This hook skips the pad read on frames that will
# not advance the sim and zeroes mTrigger(+0x1C)/mRelease(+0x20) on all four
# pads, leaving held state (mButton) intact — mirroring what stock direct()
# already does for its own non-first substeps.
#
# The 0x803DF0C8 compare is TMarDirector's VTABLE address (a runtime type check
# so the gate is inert on logo/menu/movie directors), not a rate value.
#
# The threshold is the one rate-dependent constant. A frame runs a substep when
# remainder + 10 >= quantum, i.e. remainder >= 5G - 10. The shipped v9 hardcoded
# 5, which is exactly 5*3-10 — correct at G=3 and nowhere else. CONFIRMED
# IN-GAME at G=3 (PC, 2026-08-09): the 180fps bundle shipped WITHOUT this block
# and the dropped-inputs bug returned immediately (~6/10 edge presses lost);
# re-adding the identical block fixed it — so this is default-on now, not
# opt-in. At G=2 the threshold is 0 and the remainder is always 0 (every frame
# runs a substep), so there are no skip frames to guard: the gate is
# unreachable, and emitting it would only waste cave words — return None.
# Only valid alongside substep_granularity(g), which pins budget=10/quantum=5G.
#
# select_n (the shine-select divisor, see select_gate below) adds a SECOND
# director case: when the vtable is TSelectDir's instead, pad reads are held to
# 1 frame in select_n, phase-locked to select_gate's counter. The predicate
# tests (ctr+1) % select_n because this hook runs BEFORE TSelectDir::direct in
# the frame (gameLoop: read() -> updateMeaning -> mDirector->direct()) and it
# is select_gate that increments ctr — so both gates pass on the same physical
# frame and every trigger edge is consumed by exactly one menu tick.
def input_latch(g, select_n=None):
    thresh = 5 * g - 10
    if thresh <= 0:
        return None
    if not select_n:
        words = [0x807F0004, 0x2C030000, 0x4182005C,  # mDirector; null -> read()
                 0x80830000, 0x3CA0803D, 0x60A5F0C8,  # vptr vs TMarDirector vtable
                 0x7C042800, 0x40820048,              # not TMarDirector -> read()
                 0x80830054,                          # lwz r4,0x54(r3)  accumulator
                 0x2C040000 | (thresh & 0xFFFF),      # cmpwi r4,5G-10
                 0x4080003C,                          # bge -> read()
                 0x38C00000]                          # li r6,0
        for off in (0x20, 0x24, 0x28, 0x2C):          # mGamePads[0..3]
            words += [0x80BF0000 | off, 0x90C5001C, 0x90C50020]
        words += [0x48000014,                         # b -> after the call
                  0x3D80802A, 0x618C8054, 0x7D8903A6, 0x4E800421]   # bctrl read()
        return _c2(0x802A600C, words)
    sgate = _rate_gate(select_n, ctr=4, tmp=0, tmp2=6)
    L = len(sgate)
    i_sel, i_zero, i_read, i_after = 12, 20 + L, 34 + L, 38 + L
    def beq(i, t):  return 0x41820000 | (((t - i) * 4) & 0xFFFC)
    def bge(i, t):  return 0x40800000 | (((t - i) * 4) & 0xFFFC)
    def bne(i, t):  return 0x40820000 | (((t - i) * 4) & 0xFFFC)
    def b(i, t):    return 0x48000000 | (((t - i) * 4) & 0x03FFFFFC)
    words = [0x807F0004, 0x2C030000, beq(2, i_read),  # mDirector; null -> read()
             0x80830000, 0x3CA0803D, 0x60A5F0C8,      # vptr vs TMarDirector vtable
             0x7C042800, bne(7, i_sel),               # not TMarDirector -> SEL
             0x80830054,                              # lwz r4,0x54(r3)  accumulator
             0x2C040000 | (thresh & 0xFFFF),          # cmpwi r4,5G-10
             bge(10, i_read),                         # substep frame -> read()
             b(11, i_zero)]                           # skip frame -> zero triggers
    words += [0x3CA00000 | (SELECT_DIR_VTABLE >> 16),          # SEL:
              0x60A50000 | (SELECT_DIR_VTABLE & 0xFFFF),       # TSelectDir vtable
              0x7C042800, bne(15, i_read),            # other director -> read()
              0x3CA08000,                             # lis r5,0x8000
              0x80000000 | (4 << 21) | (5 << 16) | SELECT_CTR,  # lwz r4,ctr
              0x38840001]                             # addi r4,r4,1  (predicted)
    words += sgate                                    # cr0 <- (ctr+1) % select_n
    words.append(beq(19 + L, i_read))                 # pass frame -> read()
    assert len(words) == i_zero
    words.append(0x38C00000)                          # li r6,0
    for off in (0x20, 0x24, 0x28, 0x2C):              # mGamePads[0..3]
        words += [0x80BF0000 | off, 0x90C5001C, 0x90C50020]
    words.append(b(33 + L, i_after))                  # b -> after the call
    assert len(words) == i_read
    words += [0x3D80802A, 0x618C8054, 0x7D8903A6, 0x4E800421]   # bctrl read()
    return _c2(0x802A600C, words)


# ---- Shine-select (in-stage episode select) cadence gate --------------------
# The episode/shine select screen is run by TSelectDir — a SEPARATE director:
# its direct() (USA 0x80175EC4) calls plain JDrama::TDirector::direct()
# (USA 0x802F7D28, the bl at 0x80175FE8), which fires CUE_MOVE|CUE_CALC_ANIM on
# the menu once per RENDERED frame. None of the TMarDirector gating applies, so
# the menu logic runs at 30 Hz stock but 60*G Hz under the bundle — and its
# stick-repeat timing, thresholds of the form N * (this+0x14C) ticks where
# +0x14C = 1.0/SMSGetAnmFrameRate() (computed at USA 0x801744D0, one of the §8
# "reciprocal" sites), is doubly wrong because the v11 stub pins the rate at
# 0.5. Same story for the pad's own button-repeat (TMarioGamePad::reset:
# delay 20/rate, interval 6/rate = 40/12 ticks under the stub) since read()
# free-runs at render rate on this director. Net effect at 360fps: repeat
# delay ~0.11s at 30 steps/sec — one tap of left/right skips most of the ring.
#
# Fix: hold the select-screen SIM tick (pad read via input_latch's TSelectDir
# case + the CUE_MOVE|CUE_CALC_ANIM testPerform pass inside TDirector::direct)
# to 1 frame in ceil(G/2) — a 120 Hz cadence, exactly what every
# 0.5-stub-derived constant is calibrated for (the sim substep rate). At that
# cadence the menu's 40-tick repeat delay is 0.33s at 10 steps/sec — bit-exact
# stock timing — and CALC_ANIM at 120 Hz x rate 0.5 = 60 anim units/s, also
# stock. The CUE_DRAW pass (the second testPerform, 0x802F7DD0) is NOT gated
# and re-renders the frozen state every frame. Two shipped-and-user-sighted
# traps (2026-08-10) define this shape:
#   v1 skipped the whole TDirector::direct call (hook @0x80175FE8): 2-in-3
#   frames presented with no fresh render — PWM-dimmed a real 360 Hz panel to
#   ~1/3 duty ("reduced gamma") + periodic black blink from the XFB beat.
#   v2 skipped just the MOVE|CALC_ANIM testPerform: the 3D shines FLICKERED
#   translucent — TSelectShineManager enters its J3D models into the draw
#   buffers on CUE_CALC_ANIM (perform +0x37C..0x3F0: set frame from +0x3C,
#   then two virtuals = calc + entry) and the DRAW cue draws then CLEARS the
#   buffers (J3DDrawBuffer frameInit x2 at its tail) — so a draw with no
#   preceding entry draws no shines.
# Hence v3: gated frames still CALL testPerform but with r4 = CUE_CALC_ANIM
# only — entry stays alive every frame, while MOVE (input, repeat timers,
# state machine) holds the 120 Hz cadence. Safe because the CALC_ANIM
# consumers are idempotent appliers, not advancers: the shine manager
# re-stores the SAME +0x3C frame before applying, and TSelectMenu's perform
# ignores CALC_ANIM outright (its non-MOVE path handles only CUE_DRAW).
# The hook lives INSIDE the shared TDirector::direct, so it fires
# for every plain-direct director (menu/logo/movie); the vtable compare keeps
# it inert everywhere but TSelectDir. At G=2 the cadence is already 120 Hz and
# no gate is needed (the select screen was always correct at 120fps). Odd G
# rounds up: G=3 gates 1-in-2 (90 Hz, timings uniformly 4/3 of stock — mild,
# no exact divisor exists). The counter lives in the low arena next to the
# Noki pair; this block INCREMENTS it, the input_latch case only predicts (see
# there), so a --no-input-latch build degrades to fast-but-usable, not frozen.
SELECT_DIR_VTABLE = 0x803C0EF0   # TSelectDir vtable (ctor @0x80177538 stores it)
SELECT_HOOK = 0x802F7DBC         # TDirector::direct's MOVE-pass `bl testPerform`
TESTPERFORM = 0x802FCC94         # TViewObj::testPerform (r3=unk10,r4=3,r5=&gfx set)
SELECT_CTR = 0x16E8              # low arena; 0x16E0/0x16E4 = Noki (map below at WIPE_CTR)

# ---- Select-screen gradient background 30Hz gate (v4 companion) -------------
# TSelectGrad::perform (USA 0x80175560, vtable 0x803C0EC8) advances its
# background color-cycle on CUE_CALC_ANIM: three channel bytes at +0x20/21/22
# ramp by a RAW +/-2 per call (state machine at +0x10/14/18) — native 30 Hz
# work, family-B raw-rate class, NOT AnmFrameRate-scaled. The v3 CALC_ANIM
# passthrough (required for J3D shine entry, see select_gate) therefore ran it
# at full render rate: 8x-fast color cycling at 240fps, user-sighted as the
# shines "micro-flickering" against the strobing gradient. Gate the ramp body
# to 1 frame in 2G (= 30 Hz at every G) on the same select counter, READ-ONLY
# (select_gate owns the increment). Both exits jump to the function's own
# no-CALC_ANIM join (0x80175728, the cue&8 draw test), so draw is untouched.
# Only emitted alongside select_gate (G>=3): at G=2 the counter never ticks
# and gating on a frozen value could freeze the ramp entirely.
SELECT_GRAD_HOOK = 0x80175584    # the `beq -> join` after perform's cue&2 test
SELECT_GRAD_JOIN = 0x80175728    # cue&8 draw test; original beq target

def select_grad_gate(g):
    if _select_divisor(g) is None:
        return None
    n = 2 * g
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=10)
    L = len(gate)
    words = [0x40820014,                              # cue&2 set -> GATE
             0x3D800000 | (SELECT_GRAD_JOIN >> 16),   # EXIT: lis r12,hi(join)
             0x618C0000 | (SELECT_GRAD_JOIN & 0xFFFF),  # ori r12,r12,lo
             0x7D8903A6, 0x4E800420,                  # mtctr ; bctr (skip body)
             0x3D808000,                              # GATE: lis r12,0x8000
             0x80000000 | (11 << 21) | (12 << 16) | SELECT_CTR]  # lwz r11,ctr
    words += gate                                     # cr0 <- ctr % 2G
    words.append(0x40820000 | (((1 - (7 + L)) * 4) & 0xFFFC))  # != 0 -> EXIT
    return _c2(SELECT_GRAD_HOOK, words)               # == 0: fall to ramp body


def _select_divisor(g):
    """1-in-N frame divisor holding the select screen at ~120 Hz; None if 1."""
    n = (g + 1) // 2
    return n if n >= 2 else None

def select_gate(g):
    n = _select_divisor(g)
    if n is None:
        return None
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=10)
    L = len(gate)
    i_call = 11 + L
    words = [0x819E0000,                              # lwz r12,0(r30)  this->vptr
             0x3D600000 | (SELECT_DIR_VTABLE >> 16),  # lis r11,hi(vtable)
             0x616B0000 | (SELECT_DIR_VTABLE & 0xFFFF),  # ori r11,r11,lo
             0x7C0C5800,                              # cmpw r12,r11
             0x40820000 | (((i_call - 4) * 4) & 0xFFFC),  # other director -> CALL
             0x3D808000,                              # lis r12,0x8000
             0x80000000 | (11 << 21) | (12 << 16) | SELECT_CTR,  # lwz r11,ctr
             0x396B0001,                              # addi r11,r11,1
             0x90000000 | (11 << 21) | (12 << 16) | SELECT_CTR]  # stw r11,ctr
    words += gate                                     # cr0 <- ctr % n
    words += [0x41820008,                             # pass frame -> CALL (cue=3)
              0x38800002,                             # gated: r4 = CUE_CALC_ANIM only
              0x3D800000 | (TESTPERFORM >> 16),       # CALL: lis r12,hi
              0x618C0000 | (TESTPERFORM & 0xFFFF),    # ori r12,r12,lo
              0x7D8903A6, 0x4E800421]                 # mtctr ; bctrl testPerform
    assert words[i_call] == 0x3D800000 | (TESTPERFORM >> 16)
    return _c2(SELECT_HOOK, words)


# ---- Turn-around (skid U-turn) stick-freshness fix ---------------------------
# TMario::running (USA 0x8025ab04 region) enters the skid turn when the inlined
# isRunningTurnning sees |mIntendedYaw - mFaceAngle.y| > 0x471C (~100deg) with
# mForwardVel >= mTurnNeedSp (10.0).  Every term is CUE_MOVE/substep work — 120 Hz
# at every G — so the check itself is rate-invariant.  What is NOT invariant is
# STICK FRESHNESS: stock reads the pad at 30 Hz (one read per rendered frame,
# reused by all 4 substeps), so a physical stick flip lands as one big stale jump
# and the 100deg gap is guaranteed.  Under the bundle the pad is read on every
# substep frame (~120 Hz), the intendedYaw target sweeps smoothly through the
# player's real thumb roll, and doRunning's yaw pursuit (IConverge at
# mRunningRotSp 0x200..0x400/tick ~ 675 deg/s) tracks THROUGH the flip: for a
# normal >~110 ms roll the gap never crosses 0x471C and Mario arcs instead of
# skidding.  (A perfectly center-crossed <100 ms flick still works — which is
# why the bug reads as "sometimes possible, mostly not".)
#
# FIX: run the threshold compare against mFaceAngle.y from FOUR SIM TICKS AGO —
# exactly the 33 ms staleness the stock 30 Hz pad quantization gave the check —
# while leaving the actual steering pursuit (doRunning) fully fresh.  For
# deflections that never exceed the threshold the delayed face trails the
# current one by at most 4*rotSp (~20deg) DURING convergence and by 0 at rest,
# so sub-100deg steering cannot false-trigger; for real flips the extra ~20deg
# of retained lag restores the stock ~130 ms trigger window (vanilla-at-120Hz
# cuts it to ~110 ms).  The delay is the CONSTANT 4, not f(G): sim ticks are
# pinned at 120 Hz at every G (same reasoning as the Poink 40 / cogwheel 4).
#
# Mechanics: hook the inlined check's `lha r3,0x96(r31)` in running() at USA
# 0x8025AF64.  A 4-deep ring of face angles lives in the low arena at 0x80001724
# (0x1720 = last substep-counter value, 0x172C = owning TMario*), indexed by
# gpMarDirector's substep counter (+0x5C, the same word the particle parity gate
# reads).  Ring slot (ctr&3) is read (the value written 4 ticks ago) before
# being overwritten with the current face.  Two guards reseed the whole ring
# with the current face and fall back to vanilla behavior for that tick:
#   * counter delta != 1 — the previous running() tick was not the previous
#     substep (state change, pause, level load): prevents a stale pre-WAIT face
#     from false-triggering a skid on run-start;
#   * owner != r31 — a second TMario (TEMario in the Shadow Mario chase levels)
#     shares the hook: alternating actors reseed each other every tick, so both
#     silently degrade to vanilla instead of cross-contaminating.
# turnning()'s own copy of the check (USA 0x8025A874, the turn-CANCEL predicate)
# is deliberately NOT hooked: face is frozen during the turn, so delayed ==
# current there and stock cancel semantics are preserved.
# Gated on the framerate global != 0.5f, so the block is inert without the
# bundle (r0/r3/r4/r12/cr0 all dead at the hook: r3 is being overwritten, r4 is
# li'd on the next instruction, cr0 is redefined by the cmpwi that follows).
TURNAROUND_HOOK = 0x8025AF64
TURNAROUND_SCRATCH = 0x1720          # low arena: ctr u32, ring u16[4], owner u32
                                     # (slot map at WIPE_CTR; camera block is 1730+)

def turnaround_fix():
    S = TURNAROUND_SCRATCH
    return _c2(TURNAROUND_HOOK, [
        0xA87F0096,                        # lha    r3,0x96(r31)   current face (orig)
        0x3D808041,                        # lis    r12,0x8041
        0x800C67B8,                        # lwz    r0,0x67B8(r12) framerate global
        0x3C803F00,                        # lis    r4,0x3F00      0.5f
        0x7C002000,                        # cmpw   r0,r4
        0x41820064,                        # beq    OUT            stock -> inert
        0x818D9FB8,                        # lwz    r12,-0x6048(r13) gpMarDirector
        0x280C0000,                        # cmplwi r12,0
        0x41820058,                        # beq    OUT
        0x808C005C,                        # lwz    r4,0x5C(r12)   substep counter
        0x3D808000,                        # lis    r12,0x8000
        0x800C0000 | S,                    # lwz    r0,lastCtr
        0x908C0000 | S,                    # stw    r4,lastCtr
        0x7C002050,                        # subf   r0,r0,r4       delta
        0x2C000001,                        # cmpwi  r0,1
        0x800C0000 | (S + 0xC),            # lwz    r0,owner       (cr0 survives)
        0x93EC0000 | (S + 0xC),            # stw    r31,owner
        0x40820024,                        # bne    RESEED         gap in RUN ticks
        0x7C00F800,                        # cmpw   r0,r31
        0x4082001C,                        # bne    RESEED         different TMario
        0x54800F7C,                        # rlwinm r0,r4,1,29,30  (ctr&3)*2
        0x7D8C0214,                        # add    r12,r12,r0
        0xA80C0000 | (S + 4),              # lha    r0,ring[idx]   face 4 ticks ago
        0xB06C0000 | (S + 4),              # sth    r3,ring[idx]   store current
        0x7C030378,                        # mr     r3,r0          compare vs delayed
        0x48000014,                        # b      OUT
        0xB06C0000 | (S + 4),              # RESEED: ring[0..3] = current face
        0xB06C0000 | (S + 6),
        0xB06C0000 | (S + 8),
        0xB06C0000 | (S + 0xA),
        NOP,                               # OUT: falls into the branch-back
    ])


# ---- NPC talk-initiation debounce fix ---------------------------------------
# Starting a conversation (B near an NPC) is gated in TMarDirector::movement_game
# (USA 0x8029A788, runs once per SUBSTEP) by a two-phase handshake on
# director+0x128: movement_game sets bit0 ("talk NPC near this tick") and only
# opens the talk window when BIT1 is set AND the B talk-meaning edge (+0xD4 &
# 0x800) fired this frame. Bit0 is promoted to bit1 by the tail of
# changeState (USA 0x802981EC), which runs once per RENDERED frame. Under the
# substep retune those cadences diverge: at G=6 the two skip frames between
# substeps promote-then-CLEAR bit1 before the next movement_game ever runs, so
# the check can never pass — talk initiation is structurally impossible at
# 360fps (and ~50% dropped at 180: the first substep frame after each skip
# frame sees bit1 cleared). Fix: retarget the test at USA 0x8029A908 from bit1
# (rlwinm. r0,r0,0,30,30) to bit0 (rlwinm. r0,r0,0,31,31), which movement_game
# itself just set two instructions earlier. The vanilla "NPC was already near"
# debounce is still enforced upstream: the 0x800 meaning only exists when pad
# flag 0x4 was set at frame start, and only an EARLIER movement_game tick sets
# it. At G=2/stock cadence the change is behaviorally identical (bit1 == "bit0
# last frame" == NPC near, exactly when flag 0x4 is set), so it is emitted
# whenever the substep retune is — rate-independent, no cave words.
TALK_INIT_FIX = "0429A908 540007FF"
TALK_INIT_WORD = 0x540007FF

# ---- BGM tempo guard (v12) --------------------------------------------------
# JASystem outer tempo proportion reads 0.0 across some scene transitions and
# the sequence stalls; substitute 1.0. Pure value guard, no rate constant.
BGM_TEMPO_GUARD = """C231B8C8 00000003
C0030018 C1A2FA18
FC006800 40820008
C0028018 00000000"""

# DSP voice-limiter kill: DSP_LIMIT_RATIO (f32 @0x8040CDB4) misfires under the
# 2x-slowed audio DMA period and silences every sequenced BGM note on birth.
# Zeroing it removes the load-shedding heuristic. Rate-independent.
BGM_DSP_LIMIT = "0440CDB4 00000000"

# Sun lens-flare occlusion sampler: 17 synchronous GXPeekZ EFB readbacks per
# frame, N x too often at high FPS. NOP the single call. Rate-independent.
# OPT-IN ONLY (--sun-probe): profiling showed this recovers no measurable frame
# time (the Noki stall was the pollution readback, not this) and it does break
# the flare, which then draws through geometry. Kept for reference, off by
# default. See PERF-PLAYBOOK.md "MEASURE FIRST".
SUN_PROBE = "0402E28C 60000000"

# ---- EFB peek 30Hz gates (the Metal readback stall; HANDOFF-MAC-240) --------
# Profiled 2026-08-24 on the Mac at a 240 target (single-core, Delfino, user
# playing): the TOP emulation-thread stall was FramebufferManager::PeekEFBColor
# -> -[MTLCommandBuffer waitUntilCompleted]. The EFBAccessEnable=False A/B
# measured the peek cost at ~58 VPS (136.5 -> ~197). Two game-side peek sites
# exist in the whole USA dol (bl-scan against the bse-fork us.map):
#
#   TMario::drawSyncCallback  0x8024D17C — ONE GXPeekARGB per rendered frame at
#     Mario's screen pos; sets/clears bit0 of this->0x118 (the Mario-occluded
#     flag) by testing pixel alpha == 0x10. The whole body is that one flag.
#   TSunMgr::drawSyncCallback 0x8002E270 — guard byte, then the 17x GXPeekZ
#     TSunModel::getZBufValue sun-flare occlusion sampler (SUN_PROBE's target).
#
# Both results are native-30Hz state (an occlusion bit, a flare ratio): gate
# each whole callback to 1 rendered frame in FPS/30 and let skipped frames
# hold the last value. Both functions start with mflr r0, so the gated path
# can blr from the C2 cave with LR still holding the game caller (the SE30
# gate's proven shape). Clobbers r0/r11/r12/cr0 at function entry — all dead.
# This supersedes SUN_PROBE (which NOP'd the sampler call and broke the flare);
# the flare and Mario's occlusion indicator stay visually correct at 30Hz.
# BSE port: bse_peek_gate() (2026-08-27, after Bianco-online sat at the ~170
# pre-gate ceiling while offline had moved to ~315 — the gate was born a week
# after the BSE companion and never wired in).
MARIO_PEEK_HOOK = 0x8024D17C   # TMario::drawSyncCallback (map-verified)
SUN_PEEK_HOOK   = 0x8002E270   # TSunMgr::drawSyncCallback (map-verified)
PEEK_ORIG       = 0x7C0802A6   # mflr r0 — first insn of BOTH, dol-verified
MARIO_PEEK_CTR  = 0x1700       # low-arena scratch; slot map at WIPE_CTR
SUN_PEEK_CTR    = 0x1704       # (16E0/4 noki, 16E8 SE30, 16F4/8 wipe/pump)

def peek_gate(fps):
    """Gate both EFB-peek draw-sync callbacks to native 30Hz. None when FPS/30
    is not integral (no exact native cadence exists)."""
    if fps % 30 or fps < 60:
        return None
    n = int(fps // 30)
    def block(hook, ctr_off):
        w = [0x3D608000,                                        # lis  r11,0x8000
             0x80000000 | (12 << 21) | (11 << 16) | ctr_off,    # lwz  r12,ctr(r11)
             0x398C0001,                                        # addi r12,r12,1
             0x90000000 | (12 << 21) | (11 << 16) | ctr_off]    # stw  r12,ctr(r11)
        if n & (n - 1) == 0:
            w.append(_andi_(12, 12, n - 1))                     # andi. r12,r12,N-1
        else:                                                   # exact mod for N=6 etc.
            w += [_li(11, n),                                   # li    r11,N
                  _divwu(0, 12, 11),                            # divwu r0,r12,r11
                  _mullw(0, 0, 11),                             # mullw r0,r0,r11
                  _subf_(0, 0, 12)]                             # subf. r0,r0,r12
        w += [0x41820008,                                       # beq +8 -> CONT (run)
              0x4E800020,                                       # blr — gated: skip fn
              PEEK_ORIG]                                        # CONT: mflr r0
        return _c2(hook, w)
    return "\n".join([block(MARIO_PEEK_HOOK, MARIO_PEEK_CTR),
                      block(SUN_PEEK_HOOK, SUN_PEEK_CTR)])

# ---- Noki Bay pollution-counting 30Hz gate ----------------------------------
# ~39% of the emulation thread in Noki Ep.1 is blocked in synchronous GPU->CPU
# readbacks (ReadTexels / GXReadPixMetric / PeekEFBColor) driven by pollution
# degree-counting, which runs once per RENDERED frame. The counting is native
# 30Hz work, so the divisor here is N = FPS/30 = 2G, NOT G: 4 at 120fps, 6 at
# 180, 8 at 240. Gated-out frames blr immediately and hold the last count; the
# visible goop draw (the else branch) is never gated.
#
# Two independent counters in the OS low arena, so no cue-ordering assumptions:
#   0x800016E0 obj counter (ticked once per obj cue), 0x800016E4 tex counter.
# (0x80001730-0x8000176F is the camera look-up code's 0x40-byte scratch — do
# not collide. It lived at 0x16F0 until 2026-08-10, when its 0x40-byte reach —
# assumed 4 bytes in this map — stomped WIPE_CTR/AUDIO_PUMP_CTR/TURNAROUND
# and froze every wipe the camera hook ran through: the sand-castle soft-lock.)
# The shipping v1 hardcoded `andi. r0,r11,3`, i.e. 1-in-4, correct only at
# 120fps; at 180 that is not even a valid 1-in-6 test. Rebuilt on _rate_gate so
# the branch offsets track the gate length.
#
# v3 REDESIGN (2026-08-11, the M-portal late-ripples fix). v1/v2 blr'd the
# WHOLE perform on gated frames, which also skipped the model-stamp queue
# drain (calcViewMtx, USA 0x8019B16C, called at layer 0 of the tex pass:
# walks slots at this+0x34/0x38 and entry()s each model). That batched 2G
# frames of stamps per pass frame, which (a) required the v2 dedupe to avoid
# the J3D self-loop freeze, and (b) DISCARDED up to 2G-1 of every 2G
# same-model stamps — the M-portal's rainbow-surface impact ripples are
# exactly such stamps, hence "the ripples of Mario's atoms hitting the portal
# appear way later than when the dots hit" (user, 240fps). v3 gates ONLY the
# two expensive counting calls at their call sites and lets everything else —
# CRUCIALLY the drain — run every frame:
#   0x8019D8F0  bl countObjDegree (GXReadPixMetric)   -> tick objCtr, 1-in-N
#   0x8019D90C  bl calcViewMtx / drain (layer 0)      -> tick texCtr, ALWAYS
#   0x8019D91C  bl per-layer countTexDegree (ReadTexels) -> read texCtr, 1-in-N
#   0x8019D934  bl last-layer finish                  -> read texCtr, 1-in-N
# (call sites verified by disasm of perform 0x8019D8C8: obj cue rlwinm at
# +0x08, tex cue at +0x30, layer extract at +0x38, draw bl 0x801887AC never
# touched.) With per-frame drain there is no batch, so duplicates cannot
# accumulate ACROSS frames and the v2 dedupe is RETIRED — but see the v4 note
# at NOKI_QRESET below: the gated fin call still starved the queue-count
# reset, so stale entries duplicated WITHIN a pass and froze Bianco Ep.1.
# noki_copy_gate stays: it reads texCtr WITHOUT
# ticking, and texCtr still ticks exactly once per rendered frame (layer 0),
# so its phase contract is unchanged. r0/r11/r12/ctr/cr0 are dead at all four
# hooks (each replaces a bl; the caller's live state is r3/r4 args + saved
# nonvolatiles r29-r31, all untouched).
NOKI_OBJ_CTR, NOKI_TEX_CTR = 0x16E0, 0x16E4
NOKI_OBJ_CALL = (0x8019D8F0, 0x8019CA18)   # bl countObjDegree
NOKI_DRAIN_CALL = (0x8019D90C, 0x8019B16C)  # bl calcViewMtx (layer-0 drain)
NOKI_TEX_CALL = (0x8019D91C, 0x8019B3A0)   # bl per-layer counting
NOKI_FIN_CALL = (0x8019D934, 0x8019B334)   # bl last-layer finish

def _tick(ctr):
    return [0x3D808000,                                  # lis  r12,0x8000
            0x80000000 | (11 << 21) | (12 << 16) | ctr,  # lwz  r11,ctr
            0x396B0001,                                  # addi r11,r11,1
            0x90000000 | (11 << 21) | (12 << 16) | ctr]  # stw  r11,ctr

def _read_ctr(ctr):
    return [0x3D808000,
            0x80000000 | (11 << 21) | (12 << 16) | ctr]  # lwz r11,ctr

def _call(target):
    return [0x3D800000 | (target >> 16),
            0x618C0000 | (target & 0xFFFF),
            0x7D8903A6, 0x4E800421]                      # lis/ori/mtctr/bctrl

# v4 (2026-08-19, the Bianco Ep.1 FREEZE root cause — live-debugged on the PC).
# `finish` (0x8019B334) is the ONLY resetter of the two model-stamp queue
# counts: `sth 0 -> this+0x28` (the drain's stamp queue) and `-> this+0xD4`
# (the push-task queue), disasm-verified at 0x8019B390..0x8019B398. v3 gated
# the fin CALL 1-in-N while the drain stayed per-frame, so on gated frames the
# counts were never zeroed: the drain re-entered every STALE queue entry each
# frame, and the first same-model re-push made one drain pass entry() the same
# J3DModel twice -> J3D push-front self-loop (packet->next = packet) -> the
# per-frame layer draw walks it forever. Symptom: silent freeze + looping
# audio ~2s into Bianco Ep.1's intro (the moment its goop stampers activate —
# they push their ONE persistent model every frame; Noki Bay has no stampers,
# which is why it always tested clean, and transient unique-model stamps like
# the M-portal ripples never collide). Live evidence 2026-08-19: emu thread
# spinning, frozen ctrs obj=521/tex=520, backtrace ...J3D <- 0x8019B4D0
# (pollution layer draw) <- viewobj walker. ENGINE-INDEPENDENT: latent in the
# stock kit too (v3's Bianco line was never actually retested after the v2
# dedupe was retired); the two Mac/PC "BSE noki crashes" were this.
# fin must STAY gated — it also zeroes the degree accumulators, which must
# stay in phase with the gated counting — so on the SKIP path the cave now
# does the queue-count resets itself. r3 holds the queue object (mgr+0x70) at
# the fin call site and is untouched by pre/gate; r12 is dead (bl site).
#
# v5 (2026-08-19 same night): v4 alone did NOT fix it — the freeze reproduced
# IDENTICALLY (deterministic, ctrs 521/520 both runs). The surviving
# mechanism is SAME-FRAME double-push of one model: stock tolerates it only
# because the ungated counting pass draws-and-clears the buffer BETWEEN the
# two pushes; gate the counting and the duplicate survives into a single
# drain pass -> self-loop. The proven fix has existed since 2026-08-09: the
# v2 noki_dedupe() push guard (verified in-game on this exact freeze at 120).
# v3's reason for retiring it ("deletes legitimate same-frame stamps") only
# ever applied to v1's 2G-frame BATCHES; with the per-frame drain the queue
# holds at most one frame of stamps, and a same-frame same-model duplicate is
# never legitimate (it would self-loop stock J3D). The dedupe is also
# inherently self-gating: with fin running every frame (hack off) the queue
# empties between pushes and the scan never hits. Ships REQUIRED with the
# gate at every rate, stock and BSE, no guard needed. NOKI_QRESET stays
# (stock-faithful; keeps the queue 1-frame-deep so the dedupe's scan window
# is exactly "this frame").
NOKI_QRESET = [0x39800000,                      # li  r12,0
               0xB1830028,                      # sth r12,0x28(r3)  stamp-queue count
               0xB18300D4]                      # sth r12,0xD4(r3)  push-task-queue count

def _fin_call(gate, pre, guard=None):
    """The v4 fin block: [guard?][pre][gate][bne RESET][call fin][b OUT]
    [RESET li/sth/sth][OUT -> branch-back]. Gated frames skip fin but still
    zero the queue counts exactly where stock fin would have."""
    body = list(pre) + list(gate)
    body.append(0x40820018)                     # bne +24 -> RESET (skip the call)
    w = (list(guard) if guard else []) + body + _call(NOKI_FIN_CALL[1])
    w.append(0x48000010)                        # b +16 -> OUT (past the resets)
    w += NOKI_QRESET
    return _c2(NOKI_FIN_CALL[0], w)

def noki_gate(fps):
    """Pollution-counting call-site gates at native 30Hz; the stamp-queue drain
    runs every frame; gated fin frames still reset the queue counts (v4).
    None when FPS/30 is not integral."""
    if fps % 30 or fps < 60:
        return None
    n = int(fps // 30)
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=12)
    L = len(gate)
    def gated_call(hook, target, pre):
        # [pre][gate][bne SKIP][call x4][SKIP -> branch-back]
        w = pre + gate
        w.append(0x40820000 | (4 * 5 & 0xFFFC))          # bne +20 -> past the call
        w += _call(target)
        return _c2(hook, w)
    blocks = [
        gated_call(*NOKI_OBJ_CALL, pre=_tick(NOKI_OBJ_CTR)),
        _c2(NOKI_DRAIN_CALL[0], _tick(NOKI_TEX_CTR) + _call(NOKI_DRAIN_CALL[1])),
        gated_call(*NOKI_TEX_CALL, pre=_read_ctr(NOKI_TEX_CTR)),
        _fin_call(gate, pre=_read_ctr(NOKI_TEX_CTR)),
        noki_dedupe(),          # v5: REQUIRED with the gate — see the v5 note
    ]
    return "\n".join(blocks)


# ---- Noki gate COMPANION 2: pollution EFB-copy gate (v3, the vanishing-goop fix) --
# The per-layer pipeline built by TMarDirector::initECTGft is
#   drawInit -> counting cue (TPollutionManager::perform, GATED) -> TEfbCtrlTex copy
# The copy is a SEPARATE viewObj: TEfbCtrlTex::perform (USA 0x802f8bac) GXCopyTex's
# the EFB scratch rect into the layer's pollution image EVERY frame, ungated. On
# gated frames the sim never drew the rect, so the copy snapshots black scene EFB
# into the map -> the map zeroes within frames of load ("no goop in the level",
# landed stamps flash 3-7x then die). Proven 2026-08-09 by [hifps] EFBcopy->RAM
# logging: every pollution-map flush (fmt=8/I8) was sum=0 nonzero=0 at full frame
# cadence while the bathwater copy carried real content.
#
# FIX: gate the copy to the SAME cadence and phase as the counting. Hook the
# mImagePtr null-check load in TEfbCtrlTex::perform (USA 0x802F8CF8, verified:
# lwz r0,0x2c(r29); cmplwi 0; beq exit). Pollution instances are discriminated by
# mTexFmt(+0x30) == GX_CTF_R8 (0x28) — set only by initECTGft for pollution layers;
# bathwater (direct GXCopyTex), mirror and stageDisp are untouched. On gated
# frames force r0=0 so perform's OWN null-check skips the copy; RAM keeps the last
# pass-frame map. texCtr is read without incrementing, after the layer-0 counting
# cue already ticked it this frame -> phases match from the first frame.
def noki_copy_gate(fps):
    if fps % 30 or fps < 60:
        return None
    n = int(fps // 30)
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=12)   # r0/r12 free here; r11 = texCtr
    L = len(gate)
    i_bne, i_beq, i_b = 2, 5 + L, 7 + L
    i_load = 8 + L                                 # original lwz r0,0x2c(r29)
    i_out = 9 + L                                  # falls into the branch-back
    w = [0x819D0030,                               # lwz    r12,0x30(r29)  mTexFmt
         0x280C0028,                               # cmplwi r12,0x28       GX_CTF_R8?
         0x40820000 | (((i_load - i_bne) * 4) & 0xFFFC),
         0x3D808000,                               # lis    r12,0x8000
         0x80000000 | (11 << 21) | (12 << 16) | NOKI_TEX_CTR]  # lwz r11,texCtr
    w += gate                                      # cr0 <- texCtr % n
    w += [0x41820000 | (((i_load - i_beq) * 4) & 0xFFFC),      # beq -> allow copy
          0x38000000,                              # li r0,0: pretend no image
          0x48000000 | (((i_out - i_b) * 4) & 0x03FFFFFC),     # b past the load
          0x801D002C]                              # lwz r0,0x2c(r29) (original)
    return _c2(0x802F8CF8, w)


# ---- Noki gate COMPANION: model-stamp dedupe (v2, the Bianco freeze fix; ----
# ---- RETIRED by v3 2026-08-11, REINSTATED as part of v5 2026-08-19 — v3's ----
# ---- no-batching argument missed the same-frame double-push case)         ----
# Gating TPollutionManager::perform lets pushModelStampTask accumulate G frames
# of tasks, so the SAME J3DModel is queued up to G times. calcViewMtx then calls
# model->entry() once per queue slot, and J3D's entry() is a push-front onto an
# intrusive list: the second entry of the same packet makes packet->next point
# at itself. J3DDrawBuffer::draw() walks that self-loop forever, streaming one
# mat packet into the GX FIFO until Dolphin's vertex batch OOMs (~64GB) — the
# every-time freeze on load in Bianco Ep.1 (any polluted level whose actors
# stamp models; Noki Bay has none, which is why the gate tested clean there).
# Root-caused 2026-08-09 from a live FIFO dump: the ring held one ~95-byte
# packet (CALL DL 80abc880/815fb2e0 + matrix loads) repeating wall-to-wall.
#
# FIX: dedupe at the push. Hook pushModelStampTask (USA 0x8019B120, verified:
# lhz r0,0x28(r3); cmplwi 0x14; bgelr) and scan the queue (slots of 8 at
# this+0x38) for the incoming model ptr (r5); on a hit, blr — identical to the
# stock queue-full early-return. Clobbers only volatile r10-r12; ctr untouched
# (callers may loop on it); exits with r0 = count (the re-executed original).
# fps-independent: duplicates exist whenever the gate batches frames.
def noki_dedupe():
    return _c2(0x8019B120, [
        0xA0030028,   # lhz   r0,0x28(r3)     original insn; count
        0x39630038,   # addi  r11,r3,0x38     cursor = &slot[0].mModel
        0x7C0C0378,   # mr    r12,r0          remaining = count
        0x280C0000,   # loop: cmplwi r12,0
        0x4182001C,   # beq   cont
        0x814B0000,   # lwz   r10,0(r11)
        0x7C0A2840,   # cmplw r10,r5
        0x4D820020,   # beqlr                 duplicate -> skip push
        0x396B0008,   # addi  r11,r11,8
        0x398CFFFF,   # addi  r12,r12,-1
        0x4BFFFFE4,   # b     loop
        0x60000000,   # cont: nop (falls into branch-back)
    ])


# ---- SE frame-process 30Hz gate (hover / rope creak / tentacle / ALL of them)
# Actors request repeating SEs on EVERY move tick: TWaterGun::emit (PO_HOVER,
# PO_WATER_HI, PO_NORMAL_NOZZLE_IMI), TCogwheel::control (OBJ_MR_TSUBO_PULL,
# USA 0x801da1ec), TBGTentacle (BS_GESO_TAKEN_HAND, bgtentacle.cpp:1404), and
# dozens more. The request flood is rate-invariant; the AUDIBLE cadence comes
# from JAudio's per-rendered-frame SE processing pair (JAIGFrameSe.cpp):
#   JAIBasic::checkNextFrameSe     — releases continuous SEs still in state 5
#       (unrefreshed), starts pending ones, ticks one-shot lifetimes (--unk2)
#   JAIBasic::sendPlayingSeCommand — resets refreshed (4) sounds back to 5,
#       advances per-sound frame counters (unk14++, drives pitch evolution),
#       resends distance/volume params
# A request while the sound is in state 5 refreshes it (5->4, keep-alive); a
# SECOND request before the next process stop+restarts it (JAISeEntry::
# storeBuffer). So every repeating SE audibly retriggers once per PROCESSED
# frame: 30/sec stock, FPS/sec hacked — hover putter, rope ratchet and
# tentacle squeak all run FPS/30 x too fast. Gating the PROCESS to 1 rendered
# frame in FPS/30 restores the native cadence for every SE in the game at
# once, and also returns one-shot lifetimes and pitch counters to native.
#
# Both hooks early-blr before the prologue executes (first insn is mflr r0;
# LR still holds the caller — blr is a clean skip; r0/r11/r12/cr0 are all
# volatile at a function boundary). checkNextFrameSe is called only when the
# init state allows (unk38->unk1 >= 4) but sendPlayingSeCommand runs
# unconditionally and FIRST... no: processFrameWork calls checkNextFrameSe
# BEFORE sendPlayingSeCommand, so the send hook OWNS the counter (increment +
# store) and the check hook tests counter+1 WITHOUT storing — both then pass
# on exactly the same rendered frames, in their natural order.
#
# Both USA entries are vtable-verified (slots 0x803ac4dc/f0 and 0x803e2500/14
# point at them; no derived override exists — the 0xC00-mask state tests
# appear nowhere else in the dol), so the hook covers all dispatch.
#
# Scratch counter 0x800016E8 (16E0/16E4 = Noki gates, 16F0 = camera scratch).
#
# This SUPERSEDES the same-day per-site cogwheel gate v1 (C2 @0x801DA1E8/860):
# request-side gating starves the keep-alive window — at 120fps the sound is
# released between gated requests and restarts every other frame, 60/sec
# chop instead of the native 30. Never re-add per-site SE request gates.
SE30_CHECK_HOOK = 0x80305204   # JAIBasic::checkNextFrameSe      (JP 0x8004FACC)
SE30_SEND_HOOK  = 0x80305958   # JAIBasic::sendPlayingSeCommand  (JP 0x80050220)
SE30_ORIG       = 0x7C0802A6   # mflr r0 — first insn of BOTH functions
SE30_CTR        = 0x16E8       # low-arena scratch, offset from 0x80000000

def se_frame_gate(fps):
    """Gate the JAudio SE frame-process pair to 1 rendered frame in FPS/30.
    None when FPS/30 is not integral (no exact native cadence exists)."""
    if fps % 30 or fps < 60:
        return None
    n = int(fps // 30)
    def block(hook, store):
        w = [0x3D608000,                             # lis   r11,0x8000
             0x80000000 | (12 << 21) | (11 << 16) | SE30_CTR,   # lwz r12,ctr(r11)
             0x398C0001]                             # addi  r12,r12,1
        if store:
            w.append(0x90000000 | (12 << 21) | (11 << 16) | SE30_CTR)  # stw
        if n & (n - 1) == 0:
            w.append(_andi_(12, 12, n - 1))          # andi. r12,r12,N-1
        else:                                        # exact mod for N=6 etc.
            w += [_li(11, n),                        # li    r11,N
                  _divwu(0, 12, 11),                 # divwu r0,r12,r11
                  _mullw(0, 0, 11),                  # mullw r0,r0,r11
                  _subf_(0, 0, 12)]                  # subf. r0,r0,r12
        w += [0x41820008,                            # beq   +8 -> CONT (run)
              0x4E800020,                            # blr   — gated: skip whole fn
              SE30_ORIG]                             # CONT: mflr r0 (original)
        return _c2(hook, w)
    return "\n".join([block(SE30_CHECK_HOOK, store=False),
                      block(SE30_SEND_HOOK,  store=True)])


# ---- Ricco hook/gondola slide-clank cadence (the 240fps "womp womp" wall) ----
# TRiccoHook::perform (USA 0x800c7a54; located via the live vtable 0x803B8344 —
# decomp RiccoHook.cpp is a stub) requests the crane slide clank on EVERY move
# tick once mTimer(+0x154) reaches 0, and nothing ever re-arms the timer, so
# each of Ricco Harbor's four cable hooks (the ride-basket "gondola" hangs from
# one) floods requests forever. The id is MSD_SE_OBJ_CRANE_SIDEMOVE1 0x3034 or
# _SIDEMOVE2 0x3035 picked by mInstanceIndex(+0x7C) parity — per-hook variety,
# NOT a time alternation. Stock the flood collapses to one audible retrigger
# per rendered frame = the designed 30/sec harbor clank; hacked, the retrigger
# follows the render rate — "womp womp womp, a little staticy, faster the more
# fps" (240fps report, 2026-08-10). Confirmed live with the full 240 bundle
# INCLUDING the 30 Hz audio-pump gate, so the pump alone does not tame this
# site and it needs the per-site treatment (cogwheel class).
#
# FIX: gate the SE block to 1 rendered frame in FPS/30, keyed on the audio
# pump's own low-arena frame counter (AUDIO_PUMP_CTR, incremented once per
# rendered frame at MSound::mainLoop entry, before the pump's own modulo).
# Keying that counter caps requests at the native 30/sec wall-clock AND lands
# them near pump-processed frames, and it stays correct whether the perform
# tick turns out substep-paced or render-paced. Gated ticks bctr to the
# function's own common exit (the epilogue both SE paths fall through to); the
# mTimer bookkeeping sits ABOVE the hook and is untouched. Clobbers only
# r0/r11/r12/cr0/ctr — r11 is unused in the whole function, r12 is dead since
# the vtable dispatch, cr0 is redefined by the very next game instruction, ctr
# is never used there. Fail-open: without the pump cave the counter stays 0,
# the modulo passes every tick, and behavior is exactly stock.
RICCOHOOK_HOOK = 0x800C7AB8     # lha r0,0x7C(r29) — sole entry to both SE sites
RICCOHOOK_SKIP = 0x800C7B28     # the function's common exit (epilogue restore)
RICCOHOOK_ORIG = 0xA81D007C     # the overwritten lha, dol-verified

def riccohook_se_gate(fps):
    """Hold the Ricco hook slide-clank SE at native 30/sec. None when FPS/30 is
    not integral (no pump counter exists to key on)."""
    if fps % 30 or fps < 60:
        return None
    n = int(fps // 30)
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=12)
    words = ([0x3D808000,                                       # lis  r12,0x8000
              0x80000000 | (11 << 21) | (12 << 16) | AUDIO_PUMP_CTR]  # lwz r11,ctr
             + gate                                             # cr0 <- ctr % n
             + [0x41820014,                                     # beq +0x14: pass frame
                0x3D800000 | (RICCOHOOK_SKIP >> 16),            # gated: exit through
                0x618C0000 | (RICCOHOOK_SKIP & 0xFFFF),         # the fn's own epilogue
                0x7D8903A6, 0x4E800420,                         # mtctr r12 ; bctr
                RICCOHOOK_ORIG])                                # pass: original lha
    return _c2(RICCOHOOK_HOOK, words)


# ---- Boid flocking gate (the Gelato reef red-coin fish flee at FPS/30 x) ----
# TBoidLeader::perform (USA 0x80005D14, JP-size-identical 0x168) runs the whole
# flocking update — inlined updateGoal + bl calcBoids @0x80005F60 — on the
# CALC_ANIM cue, i.e. once per RENDERED frame. calcBoids moves every boid a
# FIXED-size step (pos += dir * (speed + jitter) * |force|, boid.cpp) with no
# delta-time anywhere, and calcForces replaces the steering force with a
# straight away-from-Mario vector whenever a boid is inside the leader's flee
# radius. TFishoid::load (USA 0x80006E88) sets that radius to 400 units with
# flee strength 3.0 and tows a REAL red coin on the last boid — the "Red Coins
# of the Coral Reef" coin. At FPS the update runs FPS/30 x too often, so the
# school swims, re-aims AND applies the repellent at 4x (120fps): the coin
# outruns Mario's swim speed (user-sighted 2026-08-18, Gelato reef). The same
# leader drives butterfly clouds — gating fixes their 4x flutter drift too.
#
# FIX: hold the update at native 60 Hz. Hook the `cue & CALC_ANIM` test at
# perform+8 (0x80005D1C: rlwinm. r0,r4,0,30,30, dol-verified) and on gated
# ticks force the test result to EQ (andi. r0,r4,0) so the function's own
# guarding beq (+0x14, to its epilogue) exits before any flocking work; pass
# ticks re-execute the original test untouched.
#
# CADENCE — the v1 mistake: v1 used the Noki-style FPS/30 frame divisor
# (1-in-4 at 120fps) on the pump counter, on the assumption the native rate
# was 30 Hz. In-game (2026-08-18) that made the school visibly ~2x SLOW and
# reaction-lagged — so the native rate is 60 Hz, exactly the JPA precedent:
# the CALC_ANIM cue tree is dispatched per director substep (~120 Hz pinned
# at every G by the substep retune), and stock dispatches it at 60 Hz (the
# 60 Hz direct()/VI field loop), which is why the particle parity fix is the
# CONSTANT 1-in-2 keyed on the director substep counter. The boid update
# rides the same cue, so it gets the same gate: parity 2 on gpMarDirector's
# substep counter (+0x5C) = 60 Hz at every G. A per-frame counter would also
# be wrong at G>=3 (calls are 120 Hz, frames are 60G Hz — the residues skew).
# NOT keyed per-call: perform runs once per live TBoidLeader instance per
# tick (fish schools + butterflies), so a self-ticked counter would divide
# the cadence by instance count and freeze some leaders outright.
# Clobbers r11/r12 (dol-verified dead: prologue mflr/stw only) and r0/cr0,
# both redefined by the test instruction itself on either path. Fail-open:
# null director -> stock test runs.
BOID_HOOK = 0x80005D1C          # TBoidLeader::perform cue-test (entry + 8)
BOID_ORIG = 0x548007BD          # rlwinm. r0,r4,0,30,30 (cue & CUE_CALC_ANIM)
BOID_LWZ_DIRECTOR = 0x818D9FB8  # lwz r12,-0x6048(r13)  gpMarDirector
BOID_LWZ_SUBSTEP = 0x816C005C   # lwz r11,0x5C(r12)     director substep ctr

def boid_gate(fps):
    """Hold the TBoidLeader flocking update (fish schools + the towed Gelato
    red coin, butterflies) at native 60 Hz: parity 2 on the director substep
    counter, constant at every G (the JPA particle-parity cadence)."""
    if fps < 60:
        return None
    words = [BOID_LWZ_DIRECTOR,     # lwz    r12,-0x6048(r13)
             0x280C0000,            # cmplwi r12,0
             0x41820018,            # beq +0x18: no director -> stock test
             BOID_LWZ_SUBSTEP,      # lwz    r11,0x5C(r12)
             0x71600001,            # andi.  r0,r11,1   parity 2 = 60 Hz
             0x4182000C,            # beq +0xC: even tick -> run the update
             0x70800000,            # gated: andi. r0,r4,0 -> cr0=EQ, perform's
                                    #  own beq exits via its epilogue
             0x48000008,            # b -> branch-back slot
             BOID_ORIG]             # pass: original rlwinm. r0,r4,0,30,30
    return _c2(BOID_HOOK, words)


# ---- Test5 morph-wipe EFB-copy reduction (the decompose/recompose lag) ------
# The scene-transition "decompose/recompose" effect is the Hx wipe module's
# Hx_Test5 (USA 0x8017DF74; whole TU maps JP-0xC0388, verified against the fn
# table at 0x803C129C and Hx_CameraInit). Every RENDERED frame in wipe state 2
# it walks the screen in 64x64 tiles (10x8 = 80) and, PER TILE, calls
# Hx_GetFrBuffer (0x80182A20) = GXSetTexCopySrc/Dst + GXCopyTex(clear=TRUE) +
# GXPixModeSync — an EFB copy into the static 8KB tile buffer at 0x803F4440
# (globals 0x803F43C0 + 0x80) — then redraws the tile as a 16-segment swirled
# fan. 80 EFB copies/frame is native-30fps work: 2,400 copies/s by design,
# 28,800/s at 360fps. Each copy is a render-pass switch in Dolphin, so the
# framerate collapses for exactly the ~20 rendered frames the wipe runs
# (Hx_TimerCountDown counts frames, +0x3C = 20), which is why the recompose
# crawls while Mario (substep-scheduled) plays normally underneath. Test4 and
# the fade wipes do no copies; Circle and Door do 1-5 small morph copies per
# frame (__Hx_FrBufferMorf / Hxs_FrBufferMorf2/2B) — all fine. Test5 is the
# only monster.
#
# FIX: double the tile grid to 128x128 (5x4 = 20 copies/frame, a 4x cut) using
# the GX half-scale copy idiom so the 8KB buffer still fits: src rect 128x128,
# GXSetTexCopyDst(64, 64, fmt, mipmap=TRUE) box-filters the copy to the same
# 64x64 texture the fan already samples at normalized coords. Visual delta:
# transition chunks are 2x coarser and tile content is half-res DURING the
# morph only — imperceptible in motion; the final reveal frame hands back the
# normally-rendered scene.
#
# The copy-size change lives in ONE atomic cave (hooking the bl GXSetTexCopySrc
# inside Hx_GetFrBuffer, discriminated by dest == Test5's buffer — the other
# callers pass heap pointers) so a silently-dropped C2 can never pair "src
# widened" with "dst not halved": that pairing would GXCopyTex 16-32KB over the
# 8KB buffer and stomp BSS. Drop modes are all safe: cave dropped -> fully
# stock captures (strides/f22 alone just leave un-animated gaps during the
# wipe); strides dropped -> stock. Registers: r12/ctr free at the hook (GX
# leaf calls, Test5's own r24-r31 are behind GetFrBuffer's frame), r29 = dest
# is GetFrBuffer's own saved nonvolatile so it survives the bctrl — the flag
# is recomputed after the call instead of parked in a volatile.
#
# Emitted at G >= 3: at 120fps the 4x copy rate never measurably dipped (M2
# Max held 119), so the stock 64px look is kept there.
WIPE5_BUF = 0x803F4440          # Test5's static tile buffer (globals + 0x80)
GX_SETTEXCOPYSRC = 0x8035E388   # writes BP 0x49/0x4A (copy src TL/WH)
GX_SETTEXCOPYDST = 0x8035E48C   # (w, h, fmt, mipmap) — mipmap = half-scale
WIPE5_GRAB_HOOK = 0x80182A5C    # Hx_GetFrBuffer's bl GXSetTexCopySrc
WIPE5_RESUME = 0x80182A74       # past the original GXSetTexCopyDst call

def wipe5_opt():
    grab = _c2(WIPE5_GRAB_HOOK, [
        0x3D800000 | (WIPE5_BUF >> 16),        # lis   r12,hi(tile buffer)
        0x618C0000 | (WIPE5_BUF & 0xFFFF),     # ori   r12,r12,lo
        0x7C1D6040,                            # cmplw r29,r12    Test5's capture?
        0x4082000C,                            # bne   CALL       other caller: stock
        _rlwinm(5, 5, 1, 0, 30),               # slwi  r5,r5,1    src w 64 -> 128
        _rlwinm(6, 6, 1, 0, 30),               # slwi  r6,r6,1    src h 64 -> 128
        0x3D800000 | (GX_SETTEXCOPYSRC >> 16), # CALL: lis/ori/mtctr/bctrl
        0x618C0000 | (GX_SETTEXCOPYSRC & 0xFFFF),
        0x7D8903A6, 0x4E800421,                # GXSetTexCopySrc(x, y, srcw, srch)
        0x57C3043E,                            # clrlwi r3,r30,16  dst w = 64 (orig)
        0x57E4043E,                            # clrlwi r4,r31,16  dst h = 64 (orig)
        0x38A00004,                            # li    r5,4        GX_TF_RGB565 (orig)
        0x38C00000,                            # li    r6,0        mipmap off (orig)
        0x3D800000 | (WIPE5_BUF >> 16),        # re-test dest (r29 nonvolatile;
        0x618C0000 | (WIPE5_BUF & 0xFFFF),     #  volatiles died in the bctrl)
        0x7C1D6040,                            # cmplw r29,r12
        0x40820008,                            # bne   DST
        0x38C00001,                            # li    r6,1        half-scale copy
        0x3D800000 | (GX_SETTEXCOPYDST >> 16), # DST: lis/ori/mtctr/bctrl
        0x618C0000 | (GX_SETTEXCOPYDST & 0xFFFF),
        0x7D8903A6, 0x4E800421,                # GXSetTexCopyDst(64, 64, fmt, mip)
        0x3D800000 | (WIPE5_RESUME >> 16),     # resume past the original dst call
        0x618C0000 | (WIPE5_RESUME & 0xFFFF),
        0x7D8903A6, 0x4E800420,                # mtctr; bctr
    ])
    f22 = _c2(0x8017E18C, [0xC2C2B9FC,         # lfs f22,-0x4604(r2) = 32 (orig)
                           _fadds(22, 22, 22)])  # f22 = 64: half-tile offset/radius
    strides = "0417E39C 3B5A0080\n0417E3D8 3B390080"   # x/y tile strides 64 -> 128
    return "\n".join([grab, f22, strides])


# ---- Wipe pacing gate (the "map loads way too fast" fix) --------------------
# Every Hx wipe times itself in RENDERED frames: each wipe fn stores a hardcoded
# frame count into globals+0x3C (Test5 = 20, Test4 = 38, Circle = 25/30, Logo,
# GameOver, ... — a full-TU sweep found ONLY immediates plus two movie-struct
# counts) and ends when Hx_TimerCountDown (0x80181E58) has decremented it to 0;
# the sweep/slide wipes additionally advance Hx_MotionSet-built motion structs
# once per call to Hx_MotionUpdate (0x80181D74). NOTHING in the TU reads the
# rate (globals+0x18), the elapsed accumulator (+0x14) or the duration (+0x1C)
# that TSMSFader passes in — the seconds-scaled duration Hx_StartWipe stores is
# dead weight. So every wipe is calibrated for the stock 30fps render rate and
# runs FPS/30 = 2G x too fast under the bundle: the level-entry decompose/
# recompose (Test5, wipe ids 5/6) collapses from 0.67s to 55ms at 360fps — the
# "map loads way faster" symptom (it was masked before wipe5_opt because the 80
# EFB copies/frame tanked the framerate for exactly those 20 frames).
#
# FIX: hold the wipe CLOCK, not the wipe DRAW, to native 30 Hz. A low-arena
# counter ticks once per rendered wipe frame in Hx_UpdateWipe's state-2 body
# (hook the `stfs f31,0x18(r31)` at 0x80181F7C, just before the blrl into the
# wipe fn), and the two shared timing helpers pass 1 frame in N = FPS/30:
#   * Hx_TimerCountDown: hook the decrement (`addi r0,r3,-1` @0x80181E70,
#     reached only when the timer is nonzero) — gated frames store the timer
#     back unchanged. Callers that decrement multiple times per frame (Logo
#     calls it 4x back-to-back) keep their stock ratio: all-or-nothing per
#     frame preserves -4 per pass frame = stock -4 per 30Hz frame.
#   * Hx_MotionUpdate: hook the entry (`lfs f0,0(r3)` @0x80181D74) — gated
#     frames skip the whole advance and bctr to the tail (0x80181DD8:
#     lfs f1,0x20(r3); blr) so the caller still gets the current value.
# The draw path is untouched: wipe fns run and re-render every frame from
# frozen state (the select_gate lesson: gate cadence, never presentation).
# Coverage is airtight because BOTH helpers' 39 call sites live inside wipe
# fns, wipe fns are reachable ONLY via Hx_UpdateWipe's fn-table blrl (zero
# direct bl anywhere in .text), and Hx_UpdateWipe's one caller is TSMSFader::
# drawWipe, once per rendered frame. The one outside entry, Hx_MovieStartSyncEx
# (bl from 0x802B5CF4), calls neither helper. Counter phase is shared by both
# helpers, so timer and motion advance on the same frames, exactly like stock;
# a fresh wipe waits at most N-1 frames (< 33ms) for its first tick.
#
# The divisor is FPS/30 (render-rate class, like the Noki gate — NOT the
# substep-pinned constants): the wipe clock must match the RENDER rate ratio.
# Emitted whenever FPS is a multiple of 30 >= 60; the bug exists at 120fps too
# (wipes 4x fast) even though nobody reported it before 240/360 made it silly.
# Low-arena slot map (KEEP CURRENT — a stale copy of this map caused the
# 2026-08-10 sand-castle wipe soft-lock): 16E0/16E4 Noki, 16E8 select,
# 16F4 wipe, 16F8 pump, 1720-172F turnaround, 1730-176F camera look-up
# (0x40-byte block owned by the hand-written Gecko code, NOT this script).
WIPE_CTR = 0x16F4               # low arena; see slot map above
WIPE_TICK_HOOK = 0x80181F7C     # Hx_UpdateWipe state 2: stfs f31,0x18(r31)
WIPE_TIMER_HOOK = 0x80181E70    # Hx_TimerCountDown: addi r0,r3,-1
WIPE_MOTION_HOOK = 0x80181D74   # Hx_MotionUpdate entry: lfs f0,0(r3)
WIPE_MOTION_TAIL = 0x80181DD8   # its tail: lfs f1,0x20(r3); blr

WIPE5_SUBSTEP_LATCH = 0x16EC    # low arena: last director substep ctr seen by
                                # the Test5 sim-clock (see slot map above)

def wipe_pace(fps, smooth56=False):
    """Hold the Hx wipe clock at native 30 Hz. None when FPS/30 is not integral.
    smooth56: wipe ids 5/6 (Test5) leave the frame gate entirely and decrement
    by the DIRECTOR SUBSTEP DELTA instead (gpMarDirector+0x5C, pinned 120 Hz) —
    REQUIRED (and only valid) with wipe5_smooth()'s 80-substep constants.
    Frame-counted pacing (both the v1 30Hz gate and the first smooth attempt's
    20*(FPS/30) frames) is only correct when the host actually delivers the
    target fps; during the recompose the renderer sags (load stutter + effect
    cost) and a frame-counted wipe stretched ~2x while substep-clocked Mario
    barely slowed — the user's "recomp is 2x slow / Mario is faster than it"
    (240fps, 2026-08-11). Tying the wipe to the SAME clock as Mario makes the
    ratio exact by construction at every delivered framerate: 80 substeps
    = 0.667s of SIM time, stepping at 120 Hz (the sim's own granularity).
    Delta clamp: >2 (stale latch from the previous wipe, pause, reset) -> 1;
    result clamped >= 0 so the u32 timer can never wrap past the ==0 test.
    Null-director frames fall back to the stock -1."""
    if fps % 30 or fps < 60:
        return None
    n = int(fps // 30)
    tick = _c2(WIPE_TICK_HOOK, [
        0xD3FF0018,                                    # stfs f31,0x18(r31) (orig)
        0x3D808000,                                    # lis  r12,0x8000
        0x80000000 | (11 << 21) | (12 << 16) | WIPE_CTR,   # lwz r11,ctr
        0x396B0001,                                    # addi r11,r11,1
        0x90000000 | (11 << 21) | (12 << 16) | WIPE_CTR])  # stw r11,ctr
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=12)
    L = len(gate)
    def beq(at, to):  return 0x41820000 | (((to - at) * 4) & 0xFFFC)
    def ble(at, to):  return 0x40810000 | (((to - at) * 4) & 0xFFFC)
    def bge(at, to):  return 0x40800000 | (((to - at) * 4) & 0xFFFC)
    def b(at, to):    return 0x48000000 | (((to - at) * 4) & 0x03FFFFFC)
    pre = []
    if smooth56:
        pre = [0x3D80803F,                             # lis    r12,0x803F
               0x896C43D1,                             # lbz    r11,0x43D1(r12) wipe id
               0x380BFFFB,                             # addi   r0,r11,-5  (5->0, 6->1)
               0x28000001,                             # cmplwi r0,1
               0]                                      # ble -> DELTA (patched below)
    P = len(pre)
    i_pass, i_skip = P + 5 + L, P + 6 + L              # skip = END when not smooth
    timer = (pre
             + [0x3D808000,                            # lis  r12,0x8000
                0x80000000 | (11 << 21) | (12 << 16) | WIPE_CTR]  # lwz r11,ctr
             + gate                                    # cr0 <- ctr % n
             + [beq(P + 2 + L, i_pass),                # pass frame -> decrement
                0x38030000,                            # gated: r0 = r3 (hold timer)
                b(P + 4 + L, i_skip),
                0x3803FFFF])                           # PASS: addi r0,r3,-1 (orig)
    if smooth56:
        i_delta = len(timer) + 1                       # after the b END below
        i_dfall = i_delta + 16
        i_end = i_delta + 17
        timer[P - 1] = ble(P - 1, i_delta)             # ids 5/6 -> sim clock
        timer += [
            b(len(timer), i_end),                      # NORMAL path exits over DELTA
            0x818D9FB8,                                # DELTA: lwz r12,gpMarDirector
            0x280C0000,                                # cmplwi r12,0
            beq(i_delta + 2, i_dfall),                 # null -> stock -1
            0x818C005C,                                # lwz  r12,0x5C(r12)  substeps
            0x3D608000,                                # lis  r11,0x8000
            0x80000000 | (0 << 21) | (11 << 16) | WIPE5_SUBSTEP_LATCH,   # lwz r0,latch
            0x90000000 | (12 << 21) | (11 << 16) | WIPE5_SUBSTEP_LATCH,  # stw r12,latch
            0x7C006050,                                # subf r0,r0,r12   delta
            0x28000002,                                # cmplwi r0,2
            ble(i_delta + 9, i_delta + 11),            # sane -> use it
            0x38000001,                                # stale/garbage -> delta = 1
            0x7C001850,                                # subf r0,r0,r3    timer - delta
            0x2C000000,                                # cmpwi r0,0
            bge(i_delta + 13, i_end),
            0x38000000,                                # underflow -> 0 (end this frame)
            b(i_delta + 15, i_end),
            0x3803FFFF,                                # DFALL: stock decrement
        ]
        assert len(timer) == i_end
    motion = ([0x3D808000,                             # lis  r12,0x8000
               0x80000000 | (11 << 21) | (12 << 16) | WIPE_CTR]  # lwz r11,ctr
              + gate                                   # cr0 <- ctr % n
              + [beq(2 + L, 7 + L),                    # pass frame -> advance
                 0x3D800000 | (WIPE_MOTION_TAIL >> 16),      # gated: return the
                 0x618C0000 | (WIPE_MOTION_TAIL & 0xFFFF),   # current value via
                 0x7D8903A6, 0x4E800420,               # the fn's own tail
                 0xC0030000])                          # lfs f0,0(r3) (orig)
    return "\n".join([tick, _c2(WIPE_TIMER_HOOK, timer),
                      _c2(WIPE_MOTION_HOOK, motion)])


# ---- Test5 SMOOTH pacing (the "choppy vs 240fps-smooth Mario" complaint) -----
# wipe_pace holds the wipe clock at native 30 Hz — stock wall-clock duration,
# but also stock 30 Hz STEPPING, which reads as chop next to Mario moving at
# 240/360. For the one wipe the player actually stares at (Test5, the
# decompose/recompose), go beyond stock: instead of gating its clock, rescale
# its progress axis by N = FPS/30 so it advances a little EVERY rendered frame
# and finishes in the stock 0.67s:
#   * state-0 frame count `li r0,20` @0x8017E078 -> li r0,20*N (04, fps-baked)
#   * progress divisor: the `lfs f1,-0x4614(r2)` (pooled 20.0, shared constant
#     — cannot be edited in place) @0x8017E14C grows a C2 that multiplies by
#     2G read from the framerate global (-0x3E8(r2)): f1 = 20 * 2G = 20N. Both
#     axes scale together, so f3 = timer/(20N) sweeps 0..1 over 20N frames in
#     per-frame steps. (f0 is dead at the hook: the next read at 0x8017E164 is
#     preceded by its own lfd at 0x8017E15C.)
# REQUIRES wipe_pace(smooth56=True): ids 5/6 must be exempt from the shared
# TimerCountDown gate or the rescaled wipe runs 2Gx slow; conversely the
# exemption without this rescale runs it 2Gx fast. check() enforces pairing.
# Test5 never calls Hx_MotionUpdate, so the motion gate needs no exemption.
WIPE5_COUNT_SITE = 0x8017E078   # li r0,0x14 (state-0 frame count)
WIPE5_DIV_SITE = 0x8017E14C     # lfs f1,-0x4614(r2) (pooled 20.0)
LFS_F1_20 = 0xC022B9EC          # the overwritten original

def wipe5_smooth(fps):
    """Test5 progress on the SIM clock: 80 substeps (= stock 20 frames x 4
    substeps = 0.667s of sim time) at every fps. The matching decrement lives
    in wipe_pace(smooth56=True)'s substep-delta path. None when FPS/30 is not
    integral (no wipe_pace -> no delta path to pair with)."""
    if fps % 30 or fps < 60:
        return None
    count = f"04{WIPE5_COUNT_SITE & 0x01FFFFFF:06X} {0x38000000 | 80:08X}"
    div = _c2(WIPE5_DIV_SITE, [
        LFS_F1_20,                          # lfs   f1,-0x4614(r2) = 20.0 (orig)
        _fadds(1, 1, 1),                    # 40
        _fadds(1, 1, 1)])                   # 80: progress = timer/80
    return "\n".join([count, div])


# ---- Test5 -> Test4 swap (the SHIPPING Test5 treatment at G >= 3) -----------
# 2026-08-11: the wipe5_opt tile morph was REJECTED in playtest at 240fps. The
# user's screenshots of the boot->plaza reveal show scene chunks at wrong
# scale/position plus large black slabs. Live-RAM verification (gcmem: every
# hook word, every cave word, strides, f22 double, id-5/6 bypass) proved the
# opt/smooth blocks apply EXACTLY as designed and the $Widescreen wipe fix v2
# ortho stretch was disabled — i.e. the artifact is inherent to the 128px
# half-scale morph as Dolphin renders it, not a dropped block. Rather than
# iterate on the morph look blind, ship the pre-vetted fallback from the
# original design ("nuclear fallback, zero cost"): point wipe ids 5/6 at
# Hx_Test4 (pure sin/cos geometry, ZERO EFB copies — the door-transition wipe,
# which the user sees constantly and reported as fine). Pure data-table write.
#
# Pacing: WITHOUT the tile morph there must be NO wipe5_smooth and NO id-5/6
# timer-gate bypass — Test4's own `li 38` frame count is unscaled, so with the
# bypass it would run FPS/30 x fast. Under the plain wipe_pace 30 Hz gate it
# steps at stock cadence for its stock ~1.27s, exactly like the door wipes.
# check() enforces: swap XOR (opt + smooth + bypass).
#
# The authentic tile-dissolve could return later via a single-capture redesign
# (capture the whole 640x448 EFB once per frame into spare MEM1 above 24MB and
# draw the stock 64px fans from texcoord windows of it — 1 copy/frame instead
# of 80) — see memory/sunshine-wipe-morph-perf.md.
WIPE_FNTAB_ID5 = 0x803C12B0     # per-wipe fn-ptr table entry, id 5 (reveal)
WIPE_FNTAB_ID6 = 0x803C12B4     # id 6 (close)
HX_TEST4 = 0x8017E46C

def wipe5_swap():
    return "\n".join(f"04{a & 0x01FFFFFF:06X} {HX_TEST4:08X}"
                     for a in (WIPE_FNTAB_ID5, WIPE_FNTAB_ID6))


# ---- Audio pump 30 Hz gate (the 240fps total-music-silence fix) --------------
# MSound::mainLoop (USA 0x80014DA8, single caller: TApplication::gameLoop
# @0x802A62DC) is the game's entire per-frame audio pump: the MSSetSound/
# MSSetSoundGrp frameLoopDyna refreshers, JAIBasic::startFrameInterfaceWork
# (SE request-queue processing, continuous-SE life countdown, fades, seq/stream
# bookkeeping) and MSModBgm::loop. ALL of it is native-30Hz work: on stock
# hardware it runs once per rendered frame at 30fps, i.e. FOUR 120 Hz substep
# SE-requests collapse into every processed frame.
#
# Under the retune the pump runs at render rate while actor SE requests stay
# substep-paced (120 Hz at every G), so at 240fps the ratio INVERTS to 0.5
# requests per processed frame: every continuous SE hits processed frames with
# no fresh keep-alive request, expires, and is restarted by the next request —
# measured live (vpbdump churn) at ~300 voice births/sec with the 64-voice DSP
# pool pinned at 64/64. Every allocation then steals via breakLower/forceStop,
# and sequenced BGM notes (prio <= 126) lose the war: all 121 observed BGM-bank
# births had resampling_ratio == 0 (killed at birth). Net effect: total music
# silence at 240 (the DSP_LIMIT fix is applied and innocent — this is a second,
# independent killer with the same VPB signature). 180 survives because its
# request ratio (0.67/frame) halves the flicker rate and stays under the pool
# ceiling; the mechanism exists at every G >= 2 (the cogwheel rope-creak was
# this same class, patched per-site).
#
# FIX: gate mainLoop to 1 rendered frame in FPS/30 = native 30 Hz wall-clock.
# Hook the function's FIRST instruction (mflr r0): on gated frames LR is still
# the caller's, so a bare blr in the cave IS `return;` (same trick as the Noki
# gate). r0/r11/r12/cr0 are volatile at entry; r3 (this) untouched. Direct
# startBGM/startSound calls from game code are NOT routed through mainLoop, so
# music/SE starts enqueue regardless of gate phase and are processed <= 33ms
# later — exactly stock latency. Requests batch 4 substeps per pass frame =
# the stock invariant, at every G.
AUDIO_PUMP_CTR = 0x16F8         # low arena; see slot map at WIPE_CTR
AUDIO_PUMP_HOOK = 0x80014DA8    # MSound::mainLoop entry: mflr r0

def audio_pump_gate(fps):
    """Hold the MSound::mainLoop audio pump at native 30 Hz. None when FPS/30
    is not integral."""
    if fps % 30 or fps < 60:
        return None
    n = int(fps // 30)
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=12)
    words = ([0x3D808000,                                       # lis  r12,0x8000
              0x80000000 | (11 << 21) | (12 << 16) | AUDIO_PUMP_CTR,  # lwz r11,ctr
              0x396B0001,                                       # addi r11,r11,1
              0x90000000 | (11 << 21) | (12 << 16) | AUDIO_PUMP_CTR]  # stw r11,ctr
             + gate                                             # cr0 <- ctr % n
             + [0x41820008,                                     # beq +8: pass frame
                0x4E800020,                                     # gated: blr = return;
                0x7C0802A6])                                    # mflr r0 (orig)
    return _c2(AUDIO_PUMP_HOOK, words)


# ---- THP playback pacing (portal previews shimmer/"mirage" churn fast) ------
# The SDK THPPlayer paces display frames off the VI post-retrace callback:
# PlayControl's timing helper @0x8001EB00 computes the target movie frame as
# retraceCount64 * (movieFps*100) / 5994 (NTSC; the divisor is `li r6,0x176A`
# @0x8001EBDC feeding __div64; the PAL twin 0x1388 @0x8001EBA4 never runs on
# GMSE01). 5994 assumes retraces tick at wall-clock 59.94 Hz — but the whole
# high-fps scheme runs the console at EmulationSpeed=G, so VI retraces fire
# 59.94*G per WALL second and every THP movie plays G x fast. In-game that is
# the Delfino portal previews (data/EX128x144_q0.thp) churning at 2-6x: the
# AI-upscale's temporal shimmer crawls per movie frame ("shimmer more active")
# and the gate's correctly-paced BTK heat ripple warps over G x-fast content
# ("mirage pulses faster than normal"). It also multiplies JPEG decode load by
# G — the same decode-race pressure behind the historical brown-flash flicker.
#
# Fix: scale the divisor to 5994*G — but ONLY for silent movies. Fullscreen
# cutscene THPs carry audio mastered at the emulated rate (it rides AI/DSP at
# G x wall speed like all game audio), so slowing their video alone would
# desync them; the portal preview is the no-audio case. At the hook r31 is the
# player base (0x803EC160, set @0x8001EB14) and +0xA7 is THPPlayer.audioExist
# (zeroed @0x8001F860 in Open, set only when an audio component exists;
# readers e.g. 0x8001ED18 branch on it) — `lbz +0xA7 == 0` discriminates
# exactly. Self-gated on the framerate global != 0.5f so the block is inert if
# the fps codes are otherwise off. r7/r8/cr0 are dead here (only r3:r4 dividend,
# r5:r6 divisor survive into the bl). Full RE + address-map correction
# (ModelGate TU is USA=PAL+0x8128, NOT +0x8000):
# research/memory/sunshine-portal-preview-upscale.md (2026-08-10).
THP_PACE_HOOK = 0x8001EBDC          # PlayControl helper: li r6,0x176A (NTSC)
THP_PACE_ORIG = 0x38C0176A
THP_AUDIO_EXIST_DISP = 0xA7         # THPPlayer.audioExist, off r31 = player base

def thp_pace(fps):
    """Repace silent THP movies to wall-clock. None when G is not integral."""
    g = integer_g(fps)
    if not g:
        return None
    n = 5994 * g
    words = [THP_PACE_ORIG,                          # li   r6,0x176A (stock default)
             0x88FF0000 | THP_AUDIO_EXIST_DISP,      # lbz  r7,audioExist(r31)
             0x2C070000,                             # cmpwi r7,0
             0x4082001C,                             # bne  -> done (audio: keep sync)
             0x80E20000 | ANMRATE_GLOBAL_DISP,       # lwz  r7,framerate global(r2)
             0x3D003F00,                             # lis  r8,0x3F00 (0.5f = stock)
             0x7C074000,                             # cmpw r7,r8
             0x4182000C,                             # beq  -> done (codes off)
             0x3CC00000 | (n >> 16),                 # lis  r6,hi(5994G)
             0x60C60000 | (n & 0xFFFF)]              # ori  r6,r6,lo(5994G)
    return _c2(THP_PACE_HOOK, words)


# ---- Poink premature-explosion gate (v14, Bianco 5) -------------------------
# Poink's flight is ended early by an anim-cue-driven push to the Explosion
# nerve at flyTimer ~9; stock fires at ~36, far enough to reach Petey. Hook
# TNervePopoExplosion::execute's first-tick block: if the pig is mid-flight
# (+0xF0 bit0x80) and flyTimer(+0x19C) < 40, revert spine+0x14 to the Fly nerve
# and bctr to the epilogue, cancelling the explosion.
#
# RATE-INDEPENDENT despite the bare 40. flyTimer increments per SPINE tick, and
# the substep scheduler holds CUE_MOVE invariant across G — so flyTimer ticks at
# the same wall-clock rate at every framerate and 40 keeps meaning what it meant
# at stock. It is the anim CUE that fires G x too fast, not the timer. (Scaling
# this threshold by G would be wrong; see memory "high-fps bug surface".)
POINK = """C20E5E44 00000009
801F00F0 70000080
41820038 801F019C
2C000028 4080002C
3C008040 6000D95C
901E0014 38000001
901E0020 38600000
3C00800E 60006000
7C0903A6 4E800420
C022A460 00000000"""

# ---- Blue coin lifetime (v6) ------------------------------------------------
# G=2 ONLY, and deliberately not generalized. The gate holds TCoin::perform's
# --mStateTimer on 1 substep in 4, but the 3/4 keep ratio was *calibrated* on
# this machine against a measured ~40/sec substep rate, not derived from G (the
# sim is CPU-bound at roughly 1.33x, so the coin's substep rate is not a clean
# 60*G). Emitting it at another G would silently ship a wrong 20s timer. The
# embedded 3CE04000 gate word (float 2.0) self-disables it anywhere else anyway.
BLUECOIN = """C21BE880 00000008
3CC08041 80C667B8
3CE04000 7C063800
4082001C 80AD9FB8
28050000 41820010
80A5005C 70A50003
4182000C 901D0104
48000008 907D0104
60000000 00000000"""

# ---- HUD perpetual-stars fix (v4 = v2 + v3 + watchdog) ----------------------
# Pause/unpause leaks JPA emitters three separate ways: the coin-counter and
# pause-menu emitters are orphaned in pauseOut (v2); TPauseMenu2 re-creates the
# item sparkle every bounce loop without deleting the old one (v3); and banner
# emitters whose cleanup milestone is skipped strand forever (v4 watchdog).
# All three are rate-independent. Note the watchdog's 600.0f age threshold
# (0x44160000) is 10s only if emitters actually age at 60 Hz — which is exactly
# what _rate_gate() now guarantees at every G. Under the old fixed 1-in-2 gate
# it was 10s at 120fps but 6.7s at 180fps.
STARFIX = """C214A850 00000007
809D0124 8064011C
60630001 9064011C
806D9FB8 806300AC
80630110 28030000
41820010 8083011C
60840001 9083011C
809D0144 00000000
C2155D8C 00000004
80DF0110 28060000
41820010 80E6011C
60E70001 90E6011C
806DA024 00000000
C2324EB8 00000009
806DA024 7C03E840
40820034 807E01E8
2C030000 40820028
807E011C 70600001
4082001C 809E0010
3C004416 7C040040
4081000C 60630001
907E011C 7FC3F378
60000000 00000000"""

# ---- Heat-haze shimmer pace (catalog item 28) -------------------------------
# TShimmer::perform (USA 0x8019F83C) advances its indirect-warp BTK on every
# CUE_MOVE via a private J3DFrameCtrl pinned at rate 1.0 by init — it never
# passes through SMSGetAnmFrameRate(), so the substep retune's 120 Hz MOVE
# cadence runs the mirage 4x fast at EVERY G. Not reachable via ANMRATE_SITES
# (init's 1.0 is the only writer), hence this dedicated store hook.
# SELF-GATED: re-execs the original lwz r3,0x58(r29), then compares the
# framerate global (-0x3E8(r2)) against native 0.5f (-0x7FD8(r2)); equal ->
# stock/off -> skip. Else store 0.25f into ctrl->mRate(+0xC): 120 Hz x 0.25 =
# stock 30 anim-units/s. Under BSE the global is 2.0f != 0.5f so it activates
# there too — correct at 120 in both engines. Clobbers f0/f13/r12/cr0, all
# dead at the hook (f0 last read at 0x8019F898, cr0 redefined by the rlwinm.
# at 0x8019F8A4, r12/f13 volatile across the following bl). Emitted VERBATIM
# from research/codes/shimmer-pace-v1.txt. Default-on in the stock bundle
# (--no-shimmer to opt out) and in the --bse companion.
SHIMMER = """C219F89C 00000005
807D0058 C002FC18
C1A28028 FC006800
41820014 3D803E80
9181FFF8 C001FFF8
D003000C 00000000"""

PROXIMITY_GLOW = """C21EBA60 0000000C
816D9F4C C04B0000
C01F0010 EC420028
EDA200B2 C04B0008
C01F0018 EC420028
EDA268BA C002DDCC
EC000032 C0428028
EC0000B2 FC0D0000
40800018 C042DD68
D05F00D0 A97F00C8
B17F00CA 48000008
C05F00D0 60000000
60000000 00000000"""


# ---- Animation-rate fix (family-B "raw rate" leaks) -------------------------
# Anims whose frame-rate is set from a RAW param/const instead of through
# SMSGetAnmFrameRate() advance too fast (calc_anim runs on final substeps, which
# the substep retune pins at 120 Hz at EVERY G — 4x the native 30 Hz).  The
# correct scale for a raw rate R is therefore the CONSTANT R/4 at every G — the
# same value the ANMRATE_STUB serves API users (R * 0.5stub / 2).  An earlier
# generation divided by 2G instead: identical at G=2 (R/4, the proven v16
# x0.25), but 1.5x slow at 180 and 2x slow at 240 — calc_anim frequency is
# pinned by the retune, it does NOT scale with G.  This SUPERSEDES the
# hand-written v16 Petey block (0x800955cc is in the list below).
#
# Self-disabling: the framerate global (stock 0.5f) is compared against the
# native 0.5f constant; equal -> stock game -> skip the scale.
# The math injected at each hooked instruction (rate FPR fR, scratch fS, fT):
#     lfs   fS, -0x3e8(r2)          ; fS = G  (framerate global 0x804167B8)
#     lfs   fT, -0x7fd8(r2)         ; fT = 0.5f (native constant 0x8040EBC8)
#     fcmpu cr0, fS, fT
#     beq   +12                     ; G == 0.5 -> stock -> no-op
#     fmuls fR, fR, fT              ; R * 0.5
#     fmuls fR, fR, fT              ; R * 0.25
# store-mode  hooks the game's `stfs fR,0xc(r3)`  -> [scale] + [orig stfs]
# load-mode   hooks the `lfs f1,off(rX)` before a MActor::setFrameRate call
#             -> [orig lfs] + [scale f1]  (the original bl then stores the scaled f1)
#
# Sites confirmed by disasm sweep (animrate_disasm.py) + per-site verification.
# The stack-load site 0x80270204 (rate <- 0x120(r1), THinokuri2-area) is EXCLUDED:
# its provenance is a stack spill, not a param — needs manual confirmation first.
# r2 (SDA2) = 0x80416BA0, verified from __init_registers @0x8000536C and
# corroborated by the dolphin-gecko skill's own note that 0.5f @0x8040EBC8 is
# -0x7FD8(r2). The framerate global 0x804167B8 is therefore -0x3E8(r2).
# THIS WAS -0x3C8, which is 0x804167D8 = a plain 60.0f constant, NOT the global:
# every anmrate block computed rate/(60+60) = rate/120 instead of rate/(2G) —
# roughly 30x too slow at 120fps — and, because 60.0f is a constant, it fired
# even with the fps codes off instead of self-disabling. The in-game-confirmed
# $Petey v16 block used the absolute form (lis/lwz 0x804167B8) and was correct;
# the generator regressed it.
ANMRATE_GLOBAL_DISP = -0x3e8 & 0xFFFF          # framerate global via r2 (SDA2)
HALF_DISP = -0x7fd8 & 0xFFFF                   # native 0.5f @0x8040EBC8 via r2

def _lfs(frD, rA, d):   return (48 << 26) | (frD << 21) | (rA << 16) | (d & 0xFFFF)
def _stfs(frS, rA, d):  return (52 << 26) | (frS << 21) | (rA << 16) | (d & 0xFFFF)
def _fadds(d, a, b):    return (59 << 26) | (d << 21) | (a << 16) | (b << 11) | (21 << 1)
def _fdivs(d, a, b):    return (59 << 26) | (d << 21) | (a << 16) | (b << 11) | (18 << 1)
def _fmuls(d, a, c):    return (59 << 26) | (d << 21) | (a << 16) | (c << 6) | (25 << 1)
def _fcmpu(a, b):       return (63 << 26) | (a << 16) | (b << 11)              # cr0

# (hook_addr, mode, orig_instruction_word)
ANMRATE_SITES = [
    # getFrameCtrl + inline stfs  (rate = the stfs source FPR)
    (0x800955CC, "store", 0xD3E3000C),   # TBossPakkun::changeBck (Petey) — was v16
    (0x8013C3AC, "store", 0xD3E3000C),   # 0x8013c30c cluster (one enemy, per-anim rates)
    (0x8013C408, "store", 0xD3E3000C),
    (0x8013C46C, "store", 0xD3E3000C),
    (0x8013C24C, "store", 0xD3E3000C),   # 0x8013c1cc
    (0x8013C4E8, "store", 0xD3E3000C),   # 0x8013c490
    (0x8013C584, "store", 0xD3E3000C),   # 0x8013c52c
    (0x8013C620, "store", 0xD3E3000C),   # 0x8013c5c8
    (0x8013B6C4, "store", 0xD3E3000C),   # 0x8013b668
    (0x80244B88, "store", 0xD3E3000C),   # 0x80244800
    (0x8011763C, "store", 0xD003000C),   # 0x801175fc (rate in f0)
    (0x801176EC, "store", 0xD003000C),   # 0x801176bc (rate in f0)
    # REMOVED — the three "lfs f1,0x1d0(r31) before MActor::setFrameRate" sites
    # 0x802054D4 / 0x802054E8 / 0x80205620. Field +0x1D0 is smoothed toward a
    # target that is ALREADY multiplied by SMSGetAnmFrameRate() (0x80205530
    # `bl 0x802A7BD8` then `fmuls f30,f0,f1`, stored via the helper at
    # 0x80028BD4 hooked in at 0x80205614). Scaling the load again double-divides.
    # animrate-master.md / animrate-disasm.md only ever tagged these SUSPECT,
    # never confirmed — consistent with them being wrong.
]

def _anmrate_block(addr, mode, orig, nmul=2):
    if mode == "store":
        rate = (orig >> 21) & 31                 # stfs source FPR
        s1, s2 = (1, 2) if rate < 2 else (0, 1)  # dead volatiles != rate (post-call)
        scale = [_lfs(s1, 2, ANMRATE_GLOBAL_DISP),   # G global
                 _lfs(s2, 2, HALF_DISP),             # 0.5f
                 _fcmpu(s1, s2),
                 0x41820000 | ((nmul + 1) * 4),      # beq -> orig (stock: no-op)
                 ] + [_fmuls(rate, rate, s2)] * nmul   # R * 0.5**nmul
        words = scale + [orig]                    # original store, now of scaled rate
    else:                                        # load-mode: scale f1 after the lfs
        rate, s1, s2 = 1, 0, 13
        words = [orig,                            # original lfs f1,off(rX)
                 _lfs(s1, 2, ANMRATE_GLOBAL_DISP),
                 _lfs(s2, 2, HALF_DISP),
                 _fcmpu(s1, s2),
                 0x41820000 | ((nmul + 1) * 4),
                 ] + [_fmuls(rate, rate, s2)] * nmul
    return _c2(addr, words)

def anmrate(nmul=2, sites=None):
    """`nmul` halvings of the raw rate.  The STOCK bundle always uses 2 (x0.25):
    calc_anim is pinned at 120 Hz by substep_granularity() at every G, so the
    scale is the constant 30/120.  The BSE companion has no substep retune and
    passes log2(FPS/30) instead — see bse_anmrate().  `sites` narrows the
    emitted subset (default: all of ANMRATE_SITES)."""
    return "\n".join(_anmrate_block(a, m, o, nmul)
                     for a, m, o in (ANMRATE_SITES if sites is None else sites))


# ---- Animal movement-rate fix (birds fly at 1/4 speed) ----------------------
# The Animal family (TAnimalBase / TAnimalBird — the Delfino kamome) multiplies
# its MOVEMENT speeds by SMSGetAnmFrameRate(): fly speed, turn speed, march
# speed/accel/decel, landing approach.  That is fine for ANIM rates (calc_anim
# frequency scales with 1/rate), but animal movement is SUBSTEP-paced: kamome
# are shared-anim enemies, so TEnemyManager::performShared calls moveObject()
# on EVERY substep with no final-frame gate, and the substep clock is 120 Hz in
# stock AND in every retuned G.  Stock therefore consumes speed*2.0 at 120 Hz;
# under the stub the same 120 Hz consumes speed*0.5 -> birds fly at exactly 1/4
# speed at EVERY patched framerate.  MEASURED (240fps savestate bench,
# 2026-08-10): flying kamome 295-300 units/s patched vs ~1235 units/s stock;
# with this fix 1080-1200 units/s, wing-flap playback still the correct 60
# anim-frames/s.
#
# Fix shape: right after each movement-classified `bl SMSGetAnmFrameRate`,
# scale the returned f1 by 4 (two fadds) so downstream math sees the stock 2.0.
# Sites that square the rate (march accel/decel) reuse the same scaled f1, so
# rate^2 terms come out x16 = stock 4.0^2 automatically.  Hook = bl+4; the cave
# runs the scale THEN the original instruction (which may consume f1).
# Sweep: all 14 `bl 0x802a7bd8` sites in the Animal TU range 0x80005000-
# 0x80013000; 13 are movement (below), the 14th (0x8000AB4C) is the nerve
# duration helper handled separately by ANIMAL_DURATION.
ANIMAL_SPEED_SITES = [
    (0x80008060, 0xFFC00890),   # execWalk moving: rate saved for accel (fmr f30,f1)
    (0x80008068, 0xEC1F0072),   # execWalk: march target speed
    (0x80008078, 0xEC3F0072),   # execWalk: chase-speed arg
    (0x80008094, 0xFFC00890),   # execWalk stopping: rate saved for decel
    (0x8000809C, 0xEC1F0072),   # execWalk: decel
    (0x800080C8, 0xEC1E0072),   # execWalk: wait turn speed
    (0x800080DC, 0xEC1E0072),   # execWalk: walk turn speed
    (0x800090B4, 0xEC1F0072),   # TAnimalBase::init: initial turn speed
    (0x8000BEB4, 0xEC7F0072),   # TNerveAnimalBirdWalkOnGround: ground speed
    (0x8000CD54, 0xEFFF0072),   # TAnimalBird::doLanding: approach speed
    (0x8000CEB4, 0xEFDF0072),   # TAnimalBird::doLanding: second speed
    (0x8000D1DC, 0x819F0000),   # doFlyToCurPathNode: fly speed (lwz r12 after bl)
    (0x8000D1FC, 0xEFFF0072),   # doFlyToCurPathNode: turn speed
]

def animal_speed():
    blocks = []
    for hook, orig in ANIMAL_SPEED_SITES:
        blocks.append(_c2(hook, [_fadds(1, 1, 1), _fadds(1, 1, 1), orig]))
    return "\n".join(blocks)

# The bird-nerve duration helper @0x8000AB38 converts a param frame count via
# N * (1 / SMSGetAnmFrameRate()) — spine-tick durations for perch/flight
# nerves.  Spine ticks are substep-paced (120 Hz stock and patched), so the
# stubbed 0.5 makes every bird wait/fly phase 4x LONGER than stock (this
# masked the 1/4 fly speed: legs covered stock distance at a quarter pace).
# Scale the quotient by 0.25 to restore stock durations — but ONLY for callers
# inside the Animal TU range: the helper has two other callers (0x80211984,
# 0x8023F3D0) that are calc_anim-paced and need the stub semantics.  The hook
# reads LR (still live at the hooked fdivs) to tell them apart.
ANIMAL_DURATION_HOOK = 0x8000AB60                # fdivs f0,f0,f1 inside helper

def animal_duration():
    words = [0xEC000824,                         # fdivs f0,f0,f1 (original)
             0x7D8802A6,                         # mflr  r12      (caller+4)
             0x3D608001,                         # lis   r11,0x8001
             0x396B3000,                         # addi  r11,r11,0x3000 = 0x80013000
             0x7C0C5840,                         # cmplw r12,r11
             0x40800010,                         # bge   -> skip (non-Animal caller)
             _lfs(13, 2, HALF_DISP),             # f13 = 0.5f
             _fmuls(0, 0, 13),
             _fmuls(0, 0, 13)]                   # f0 *= 0.25
    return _c2(ANIMAL_DURATION_HOOK, words)


def framerate_word(fps):
    """float(FPS/60) as an 8-hex-digit big-endian word for the 04 write."""
    return struct.pack(">f", fps / 60.0).hex().upper()


def integer_g(fps):
    """G = FPS/60 as an int when it is exact, else None (no exact gate exists)."""
    g = fps / 60.0
    return int(round(g)) if g >= 2 and abs(g - round(g)) < 1e-9 else None


def build(fps, forceopen=True, anmrate_fix=True, substep=True, audio=True,
          stars=True, sun_probe=False, noki=True, poink=True, bluecoin=True,
          cogwheel=True, input_latch_fix=True, select_fix=True, wipe_opt=True,
          turnfix=True, wipe_pace_fix=True, audio_pump=True, thp_pace_fix=True,
          riccohook=True, wipe_swap=True, shimmer=True, boidfix=True,
          peekgate=True):
    g = integer_g(fps)
    gate_g = g or 2                            # non-integer G: fall back to 1-in-2
    parts = [base(framerate_word(fps)), particles(gate_g), PROXIMITY_GLOW]
    if forceopen:
        parts.insert(2, FORCEOPEN)
    if substep:
        # the stub is only valid while the substep retune pins the sim at 120 Hz
        parts += [substep_granularity(gate_g), ANMRATE_STUB]
        # the stub breaks substep-paced animal movement/durations — see the
        # Animal movement-rate fix; only correct alongside stub + retune
        parts += [animal_speed(), animal_duration()]
        # skip frames desync the talk-start handshake — see TALK_INIT_FIX
        parts.append(TALK_INIT_FIX)
        # ~120 Hz pad sampling lets yaw pursuit track through a stick flip and
        # starves the skid-turn threshold — see turnaround_fix (constant 4-tick
        # delay, valid only while the retune pins sim ticks at 120 Hz)
        if turnfix:
            parts.append(turnaround_fix())
        # the shine-select fix rides the same 0.5-stub calibration and needs
        # the pad-latch block for its select case — see select_gate
        sel_n = _select_divisor(gate_g) if (select_fix and input_latch_fix) else None
        if input_latch_fix:
            # the latch predicate reads the retuned accumulator — substep only
            il = input_latch(gate_g, sel_n)
            if il:
                parts.append(il)
        if sel_n:
            parts.append(select_gate(gate_g))
            parts.append(select_grad_gate(gate_g))  # REQUIRED companion — see it
    tf = timerfix(fps)
    if tf:
        parts.append(tf)
    if anmrate_fix:
        parts.append(anmrate())
    if audio:
        parts += [BGM_DSP_LIMIT, BGM_TEMPO_GUARD]
    if audio_pump:
        apg = audio_pump_gate(fps)             # render-rate class: FPS/30 divisor
        if apg:
            parts.append(apg)
    if thp_pace_fix:
        tp = thp_pace(fps)                     # VI-retrace class: G x wall speed
        if tp:
            parts.append(tp)
    if stars:
        parts.append(STARFIX)
    if poink:
        parts.append(POINK)
    if cogwheel:
        sg = se_frame_gate(fps)                # global SE 30Hz gate; supersedes cogwheel_se_gate
        if sg:
            parts.append(sg)
    if riccohook:
        rh = riccohook_se_gate(fps)            # render-rate class: FPS/30 divisor
        if rh:
            parts.append(rh)
    if boidfix:
        bg = boid_gate(fps)                    # CALC_ANIM class: constant parity 2
        if bg:
            parts.append(bg)
    if noki:
        ng = noki_gate(fps)
        if ng:
            parts.append(ng)
            # v5: noki_gate() now carries noki_dedupe() again — v3's "the
            # per-frame drain makes duplicates impossible" was disproven
            # 2026-08-19 (same-frame double-push self-loop; see the v5 note).
            parts.append(noki_copy_gate(fps))  # REQUIRED companion — see noki_copy_gate
    # Test5 treatment at G>=3 (120fps keeps the stock 64px tile morph): the
    # default is the Test4 swap (see wipe5_swap — the tile morph was rejected
    # in playtest 2026-08-11); --no-wipe-swap restores the opt+smooth morph.
    swap = wipe_swap and gate_g >= 3
    if swap:
        parts.append(wipe5_swap())
    elif wipe_opt and gate_g >= 3:
        parts.append(wipe5_opt())
    # Test5 smooth pacing pairs 1:1 with the wipe_pace id-5/6 exemption — never
    # emit one without the other (2Gx fast / 2Gx slow respectively), and never
    # either with the swap (Test4's own frame count is unscaled).
    smooth56 = bool(not swap and wipe_pace_fix and gate_g >= 3 and wipe5_smooth(fps))
    if wipe_pace_fix:
        wp = wipe_pace(fps, smooth56=smooth56) # render-rate class: FPS/30 divisor
        if wp:
            parts.append(wp)
    if smooth56:
        parts.append(wipe5_smooth(fps))
    if bluecoin and g == 2:                    # calibrated at G=2 only — see BLUECOIN
        parts.append(BLUECOIN)
    if shimmer:                                # catalog item 28: self-gated on 0.5f
        parts.append(SHIMMER)
    if peekgate:
        pg = peek_gate(fps)                    # render-rate class: FPS/30 divisor
        if pg:
            parts.append(pg)
    if sun_probe:
        parts.append(SUN_PROBE)
    return "\n".join(parts)


# ============================================================================
# BSE-120 companion bundle
# ----------------------------------------------------------------------------
# Under the "Better Sunshine Engine" online mod (BSMSO), BSE re-writes the
# framerate global 0x804167B8 EVERY frame; at BSE FPS_120 (mFPSValue=2) it
# writes float 2.0f (0x40000000). The stock fpspatch bundle is NOT usable
# there: its 04 write to 0x804167B8 is a one-shot, immediately clobbered, and
# its EmulationSpeed regime differs. Instead each fix is re-authored so its C2
# body runs ONLY when the global holds exactly 2.0f — a guard prologue reads
# 0x804167B8 and, if != 2.0f, falls straight through to the block's original
# instruction + branch-back (i.e. STOCK behavior: the gate never fires).
#
# The guard is the production-proven pattern (byte-verified in the live INI's
# particle-parity BSE code): read 0x804167B8, cmpw against 0x40000000, bne to
# the block's run-stock convergence point. Scratch here is r0 (the loaded
# value) + r11 (the 2.0f literal) + cr0 — chosen because they are dead at
# EVERY hook this companion touches: the noki call sites keep their live args
# in r3/r4 (never r0/r11 until the cave itself reloads them), the wipe timer's
# r0 is a WRITE target re-materialised by the re-executed addi, and the SE
# entries have volatile r0/r11 at a function boundary. r12 is left free for the
# block bodies that already use it as their counter base.
BSE_FPS120_WORD = 0x40000000            # float 2.0f = *0x804167B8 at BSE FPS_120
BSE_FPS240_WORD = 0x40800000            # float 4.0f = *0x804167B8 at BSE FPS_240
                                        # (fork kxe FPS_240 — see HANDOFF-PC-240)

def bse_fps_word(fps):
    """The word BSE's updateFPS() writes to 0x804167B8 every gameplay frame:
    float(FPS/60).  120 -> 0x40000000 (2.0f), 240 -> 0x40800000 (4.0f).
    The guard materialises it with a bare `lis`, so the LOW half must be zero —
    true for every G that is a power of two, which is exactly the set
    bse_build() accepts.  A non-zero low half would need an extra `ori`, which
    would shift GUARD_BNE_WORD and every target_word computed in this file."""
    w = struct.unpack(">I", struct.pack(">f", fps / 60.0))[0]
    if w & 0xFFFF:
        raise SystemExit(f"BSE guard: float({fps / 60:g}) = {w:08X} has a non-zero "
                         f"low half — the 1-instruction `lis` guard cannot hold it")
    return w

GUARD_BNE_WORD = 4                       # the bne is always the 5th guard word

def _bse_guard(target_word, base=12, val=0, lit=11, fps=120):
    """Guard prologue (5 words). `target_word` = the block-start word index of
    the run-stock convergence point (the block's re-executed original
    instruction, or the 'run the gated body' path). The bne at word 4 branches
    there; on 2.0f-equal the guard falls through into the block body at word 5.

    Register choice defaults to the proven r12(base)/r0(val)/r11(lit) triple. The
    animal_duration hook (0x8000AB60) spills a LIVE r0 one instruction later
    (the int->double 0x43300000 magic word set at 0x8000AB5C), so that block
    passes base=12, val=11, lit=12 to keep r0 untouched — both r11 and r12 are
    reloaded by the block body on the guard-pass path and are dead after the
    hook on the guard-fail path.

    `fps` selects the compared literal: 120 -> `lis rLit,0x4000` (2.0f), 240 ->
    `lis rLit,0x4080` (4.0f).  The guard is 5 words at EVERY rate, so all the
    target_word arithmetic in the callers stays valid unchanged."""
    disp = ((target_word - GUARD_BNE_WORD) * 4) & 0xFFFC
    return [(15 << 26) | (base << 21) | 0x8041,       # lis   rBase,0x8041
            (32 << 26) | (val << 21) | (base << 16) | 0x67B8,  # lwz rVal,0x67B8(rBase)
            (15 << 26) | (lit << 21) | (bse_fps_word(fps) >> 16),  # lis rLit,hi16(G)
            (31 << 26) | (val << 16) | (lit << 11),   # cmpw  rVal,rLit
            0x40820000 | disp]                        # bne   -> run-stock

# The BSE particle-parity code is emitted VERBATIM (byte-identical to the live
# INI): three 8-pair guarded blocks, the guard folded into the proven cadence
# body. Do NOT regenerate from particles()/_parity_block — those are the
# UNGUARDED stock caves. Block bodies are identical apart from the hook addr.
def _bse_parity_block(hook, fps=120):
    # Word 2 (`lis r4,hi16(float G)`) is the ONLY rate-dependent word here.
    # Word 9 is `andi. r0,r3,1` = the CONSTANT 1-in-2 JPA parity, deliberately
    # NOT scaled — see BSE_PARITY_DIVISOR below.
    return "\n".join([
        f"{hook} 00000008",
        "3C608041 800367B8",
        f"3C80{bse_fps_word(fps) >> 16:04X} 7C002000",
        "40820024 806D9FB8",
        "28030000 41820010",
        "8063005C 70600001",
        "4082000C C002DD68",
        "EC21002A FC00081E",
        "60000000 00000000",
    ])

PARITY_HOOK_WORDS = ("C22887A8", "C2288D30", "C2288DEC")

# ---- the JPA parity divisor under BSE --------------------------------------
# Held at the CONSTANT 2 at every rate, per HANDOFF-PC-240 ("parity stays
# CONSTANT 2") and commit defbcff ("particle parity is the CONSTANT 1-in-2").
#
# RESOLVED 2026-08-19 (was the one open question of the 240 generalization):
#   the gate counts gpMarDirector+0x5C, which ticks once per SUBSTEP.  The
#   bse_substep() 120 Hz sim pin (mandatory at fps > 120 — without it the
#   whole game runs fps/120 x fast, the PC playtest symptom) makes that
#   counter 120 Hz at EVERY rate, exactly like the stock kit whose
#   substep_granularity() the pin reuses.  120/2 = the native 60 Hz JPA rate,
#   so the divisor genuinely cannot scale.  (Had the pin not existed, the
#   divisor would have been fps/60 — moot now.)
def BSE_PARITY_DIVISOR(fps):
    return 2

def bse_parity(fps=120):
    n = BSE_PARITY_DIVISOR(fps)
    if n & (n - 1) or n < 2:
        raise SystemExit(f"BSE parity divisor {n} must be a power of two >= 2")
    mask = f"7060{n - 1:04X}"
    return "\n".join(
        _bse_parity_block(h, fps).replace("70600001", mask) for h in PARITY_HOOK_WORDS)

BSE_FORCE_120 = "0451E528 00000002"     # BSE mFPSValue = 2 (FPS_120)


def bse_noki_gate(fps=120):
    """noki_gate with a BSE guard on every block. Guard-fail => the gated call
    RUNS (stock: pollution counting every frame)."""
    n = int(fps // 30)                                  # 4 at 120, 8 at 240
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=12)
    L = len(gate)
    def gated_call(hook, target, pre):
        # [guard -> CALL][pre][gate][bne CALL][call x4 = CALL][branch-back]
        body = pre + gate
        body.append(0x40820000 | ((5 * 4) & 0xFFFC))    # bne +20 -> _call (run)
        call = _call(target)
        # CALL index (from guard word 0): guard(5) + body + this bne is the last
        # of `body`; _call begins right after.
        i_call = 5 + len(body)                          # start of _call = run path
        w = _bse_guard(i_call, fps=fps) + body + call
        return _c2(hook, w)
    def plain_call(hook, target, pre):
        # drain: no divisor. guard-fail -> the call (which is stock behavior).
        call = _call(target)
        i_call = 5 + len(pre)
        w = _bse_guard(i_call, fps=fps) + pre + call
        return _c2(hook, w)
    # fin (v4): guard-fail -> the fin call (stock: fin runs, resets its own
    # queues); guard-pass gated -> our queue-count resets (see NOKI_QRESET).
    # Guard target = start of _call = guard(5) + pre(2) + gate(L) + bne(1).
    fin = _fin_call(gate, pre=_read_ctr(NOKI_TEX_CTR),
                    guard=_bse_guard(8 + L, fps=fps))
    return "\n".join([
        gated_call(*NOKI_OBJ_CALL, pre=_tick(NOKI_OBJ_CTR)),
        plain_call(*NOKI_DRAIN_CALL, pre=_tick(NOKI_TEX_CTR)),
        gated_call(*NOKI_TEX_CALL, pre=_read_ctr(NOKI_TEX_CTR)),
        fin,
        noki_dedupe(),      # v5: REQUIRED; self-gating, so no BSE guard —
                            # with fin running every frame the scan never hits
    ])


def bse_noki_copy_gate(fps=120):
    """noki_copy_gate with a BSE guard. Guard-fail => the original
    lwz r0,0x2c(r29) runs (stock: EFB copy every frame)."""
    n = int(fps // 30)
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=12)
    L = len(gate)
    G = 5                                                # guard words
    i_bne = G + 2
    i_beq = G + 5 + L
    i_b = G + 7 + L
    i_load = G + 8 + L                                   # original lwz (run-stock)
    i_out = G + 9 + L                                    # branch-back slot
    w = _bse_guard(i_load, fps=fps)                      # guard-fail -> orig lwz
    w += [0x819D0030,                                    # lwz    r12,0x30(r29) mTexFmt
          0x280C0028,                                    # cmplwi r12,0x28
          0x40820000 | (((i_load - i_bne) * 4) & 0xFFFC),
          0x3D808000,                                    # lis    r12,0x8000
          0x80000000 | (11 << 21) | (12 << 16) | NOKI_TEX_CTR]  # lwz r11,texCtr
    w += gate
    w += [0x41820000 | (((i_load - i_beq) * 4) & 0xFFFC),        # beq -> allow copy
          0x38000000,                                   # li r0,0: pretend no image
          0x48000000 | (((i_out - i_b) * 4) & 0x03FFFFFC),
          0x801D002C]                                    # lwz r0,0x2c(r29) (orig)
    return _c2(0x802F8CF8, w)


def bse_se_frame_gate(fps=120):
    """se_frame_gate with a BSE guard. Guard-fail => the original mflr r0 runs
    and execution falls through into the function (stock: SE process every
    rendered frame)."""
    n = int(fps // 30)
    def block(hook, store):
        w0 = [0x3D608000,                                # lis   r11,0x8000
              0x80000000 | (12 << 21) | (11 << 16) | SE30_CTR,   # lwz r12,ctr(r11)
              0x398C0001]                                # addi  r12,r12,1
        if store:
            w0.append(0x90000000 | (12 << 21) | (11 << 16) | SE30_CTR)
        if n & (n - 1) == 0:
            w0.append(_andi_(12, 12, n - 1))
        else:
            w0 += [_li(11, n), _divwu(0, 12, 11),
                   _mullw(0, 0, 11), _subf_(0, 0, 12)]
        # [guard -> ORIG][body][beq CONT][blr][CONT: mflr r0 = ORIG]
        i_orig = 5 + len(w0) + 2                         # index of SE30_ORIG (mflr)
        w = _bse_guard(i_orig, fps=fps) + w0 + [
            0x41820008,                                  # beq +8 -> CONT (run)
            0x4E800020,                                  # blr — gated: skip fn
            SE30_ORIG]                                   # CONT: mflr r0 (orig)
        return _c2(hook, w)
    return "\n".join([block(SE30_CHECK_HOOK, store=False),
                      block(SE30_SEND_HOOK, store=True)])


def bse_peek_gate(fps=120):
    """peek_gate with a BSE guard: both EFB-peek draw-sync callbacks (Mario
    occlusion GXPeekARGB + sun-flare GXPeekZ sampler) gated to native 30Hz.
    Guard-fail => the original mflr r0 runs and execution falls through into
    the callback (stock: peek every rendered frame). Entry-hook/blr shape and
    check contract identical to bse_se_frame_gate; r0/r11/r12/cr0 are dead at
    both function entries (see the stock peek_gate analysis), so the default
    guard register triple is safe. Each hook owns its counter, so both store."""
    n = int(fps // 30)
    def block(hook, ctr_off):
        w0 = [0x3D608000,                                # lis   r11,0x8000
              0x80000000 | (12 << 21) | (11 << 16) | ctr_off,  # lwz r12,ctr(r11)
              0x398C0001,                                # addi  r12,r12,1
              0x90000000 | (12 << 21) | (11 << 16) | ctr_off]  # stw r12,ctr(r11)
        if n & (n - 1) == 0:                             # 4 at 120, 8 at 240
            w0.append(_andi_(12, 12, n - 1))
        else:                                            # unreachable under
            w0 += [_li(11, n), _divwu(0, 12, 11),        # bse_supported (N is
                   _mullw(0, 0, 11), _subf_(0, 0, 12)]   # a power of two)
        i_orig = 5 + len(w0) + 2                         # index of PEEK_ORIG
        w = _bse_guard(i_orig, fps=fps) + w0 + [
            0x41820008,                                  # beq +8 -> CONT (run)
            0x4E800020,                                  # blr — gated: skip fn
            PEEK_ORIG]                                   # CONT: mflr r0 (orig)
        return _c2(hook, w)
    return "\n".join([block(MARIO_PEEK_HOOK, MARIO_PEEK_CTR),
                      block(SUN_PEEK_HOOK, SUN_PEEK_CTR)])


# ---- jump-chain window under BSE (John's 2026-08-28 A/B) --------------------
# TMario::jumpSlipEvents (USA 0x80258D24; jumpSlipCommon 0x80258E5C): the
# double/triple-jump chain window is `mStatusTimer >= rec->mMaxTimer` with
# mMaxTimer = 16 RAW TICKS, ticked once per Mario status update. Stock cadence
# 30Hz -> ~533ms to chain; BSE runs the status machine at 120Hz (raw at 120,
# substep-pinned at 240) -> 133ms, below human reaction from the landing
# frame. John's A/B: native 30 easy / BSE-60 harder / BSE-120 impossible — the
# exact 1/(rate) curve.
#
# v1 (231e53f) scaled the LOADED threshold x4 via a C2 at the shared lha
# (0x80258D60) — which hit every record served by that load. The jumpSlip
# dispatcher (prologue 0x80258308: lis 0x803E / addi -0x2E20 -> r31 =
# 0x803DD1E0) passes SIX 20-byte JumpSlipRecords at r31+0x38..+0x9C, layout
# {s16 mMaxTimer; u32 timeout status; u32 chain status; u32 move-exit status;
# u32}:
#   +0x38 max=16 chain 0x02000881 (-> double)  +0x4C max=16 chain 0x02000881
#   +0x60 max=16 chain 0x00000882 (-> triple)  +0x74 max=16 chain 0x02000880
#   +0x88 max=4  chain 0x02000880              +0x9C max=24 chain 0x00000888
# x4 on ALL of them restored vanilla-length landing/getup recovery states that
# BSE's fast status cadence had been (pleasantly) shortening 4x — Kris's
# 2026-08-28 field report at Online 120: "a bit of a stun where I can't move"
# on landing, new the night v1 first ran.
#
# v2 drops the C2 entirely and scales ONLY the three records that feed the
# double/triple chain (+0x38, +0x4C -> 0x881; +0x60 -> 0x882) as guarded
# DATA: a Gecko 32-bit if-equal (20) on the framerate global — BSE rewrites
# it every frame, so the writes self-scope to the target rate exactly like
# the C2 guards — followed by three 16-bit writes (02) and a full terminator
# (E0). Records +0x74/+0x88/+0x9C keep stock values: their short real-time
# recovery under BSE is the desired feel, and John's verified double/triple
# A/B never depended on them. HANDOFF-JUMPCHAIN-BUG.md has the full report.
JUMPCHAIN_HOOK = 0x80258D60    # v1's C2 site — kept so --check REJECTS v1
JUMPSLIP_RECS = 0x803DD1E0     # dispatcher r31; records at +0x38..+0x9C
JUMPCHAIN_CHAIN_RECS = (0x803DD218, 0x803DD22C, 0x803DD240)  # ->881,881,882
JUMPCHAIN_STOCK = 16           # stock mMaxTimer in all three chain records

def bse_jump_chain(fps=120):
    """Scale the three chain-feeding JumpSlipRecord mMaxTimers by the
    status-machine cadence ratio bse_sim_fps(fps)/30 — 4 at BOTH kit rates
    (raw 120Hz at fps=120; the substep pin holds 120Hz at fps=240) — as data
    writes under a Gecko if-equal on the framerate global."""
    k = bse_sim_fps(fps) // 30
    want = JUMPCHAIN_STOCK * k
    lines = [f"20{FRAMERATE_GLOBAL & 0x01FFFFFF:06X} {bse_fps_word(fps):08X}"]
    for rec in JUMPCHAIN_CHAIN_RECS:
        lines.append(f"02{rec & 0x01FFFFFF:06X} {want:08X}")
    lines.append("E0000000 80008000")
    return "\n".join(lines)


def bse_wipe_pace(fps=120):
    """wipe_pace (smooth56=False) with a BSE guard on all three blocks.
    Guard-fail => wipes run STOCK (ungated): the original insn executes and the
    counter machinery is bypassed."""
    n = int(fps // 30)
    G = 5
    # tick: guard-pass -> increment the shared counter THEN the original stfs;
    # guard-fail -> straight to the original stfs (counter frozen, harmless: the
    # timer/motion gates run stock when the guard fails). The orig stfs is the
    # convergence word so both paths execute it exactly once.
    tick = _c2(WIPE_TICK_HOOK, _bse_guard(G + 4, fps=fps) + [  # fail -> orig stfs
        0x3D808000,                                     # lis  r12,0x8000
        0x80000000 | (11 << 21) | (12 << 16) | WIPE_CTR,   # lwz r11,ctr
        0x396B0001,                                     # addi r11,r11,1
        0x90000000 | (11 << 21) | (12 << 16) | WIPE_CTR,   # stw r11,ctr
        0xD3FF0018])                                    # stfs f31,0x18(r31) (orig)
    # timer: guard-fail -> the original addi r0,r3,-1 (PASS word).
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=12)
    L = len(gate)
    i_pass = G + 5 + L                                   # addi r0,r3,-1 (orig)
    i_skip = G + 6 + L                                   # branch-back slot
    timer_body = [0x3D808000,                            # lis  r12,0x8000
                  0x80000000 | (11 << 21) | (12 << 16) | WIPE_CTR]  # lwz r11,ctr
    timer_body += gate
    timer_body += [0x41820000 | (((i_pass - (G + 2 + L)) * 4) & 0xFFFC),  # beq PASS
                   0x38030000,                          # gated: r0 = r3 (hold)
                   0x48000000 | (((i_skip - (G + 4 + L)) * 4) & 0x03FFFFFC),  # b SKIP
                   0x3803FFFF]                           # PASS: addi r0,r3,-1 (orig)
    timer = _c2(WIPE_TIMER_HOOK, _bse_guard(i_pass, fps=fps) + timer_body)
    # motion: guard-fail -> the original lfs f0,0(r3), then branch-back.
    i_orig = G + 7 + L                                   # lfs f0,0(r3) (orig)
    motion_body = [0x3D808000,
                   0x80000000 | (11 << 21) | (12 << 16) | WIPE_CTR]
    motion_body += gate
    motion_body += [0x41820000 | (((i_orig - (G + 2 + L)) * 4) & 0xFFFC),  # beq -> advance
                    0x3D800000 | (WIPE_MOTION_TAIL >> 16),      # gated: return current
                    0x618C0000 | (WIPE_MOTION_TAIL & 0xFFFF),   # via the fn's own tail
                    0x7D8903A6, 0x4E800420,             # mtctr r12 ; bctr
                    0xC0030000]                          # lfs f0,0(r3) (orig)
    motion = _c2(WIPE_MOTION_HOOK, _bse_guard(i_orig, fps=fps) + motion_body)
    return "\n".join([tick, timer, motion])


# StarFix v4's three blocks, each re-executing its overwritten original as the
# LAST real word before the branch-back (all internal control paths already
# converge there): block1 lwz r4,0x144(r29) @word12, block2 lwz r3,-0x5FDC(r13)
# @word6, block3 mr r3,r30 @word15. Prepending the 5-word guard shifts every
# body word by +5 but leaves the bodies' OWN relative branches intact (they are
# position-relative); the guard's bne is aimed at the shifted original word so
# guard-fail lands exactly on the re-executed original. STARFIX uses r3-r7/r0/
# cr0; the guard's r0/r11/r12 are all reloaded or unused before use, cr0 is
# recomputed by each block's own compare.
BSE_STARFIX_ORIG_WORD = {0x8014A850: 12, 0x80155D8C: 6, 0x80324EB8: 15}

def bse_starfix(fps=120):
    out = []
    for kind, addr, body in _iter_codes(STARFIX):
        body = body[:-1]                        # drop the handler-clobbered 0 pad
        i_orig = BSE_STARFIX_ORIG_WORD[addr]
        w = _bse_guard(5 + i_orig, fps=fps) + body   # fail -> shifted original
        out.append(_c2(addr, w))
    return "\n".join(out)


# ---- Boid flocking 30Hz gate under BSE — GUARDED ---------------------------
# The offline boid_gate ported behind the standard _bse_guard so it only fires
# when BSE's framerate global holds float(G) (2.0f @120), never at native 0.5f.
#
# CADENCE: the offline gate's cadence is DELIBERATELY the CONSTANT parity-2 on
# gpMarDirector's substep counter (+0x5C) = native 60 Hz — NOT an FPS/30
# divisor (boid_gate v1's FPS/30 played the school ~2x slow, user-sighted
# 2026-08-18). Under BSE the substep pin holds that counter at 120 Hz at every
# rate, so 1-in-2 = 60 Hz exactly, same as the JPA particle parity. So the mask
# stays the CONSTANT andi. r0,r11,1 at every G — it does NOT scale with fps.
#
# STRUCTURE: reuse boid_gate's 9-word body verbatim behind the 5-word guard.
# All three of the body's internal branches are position-relative (beq +0x18,
# beq +0xC, b +8), so prepending the guard shifts every word by +5 without
# disturbing them (the StarFix pattern). Guard-fail is aimed at the re-executed
# original BOID_ORIG, now at word 5 + 8 = 13. The guard clobbers r12/r0/r11 in
# its prologue, but the body reloads r12 (from r13) and r11 (from r12) before
# use and redefines r0 on every path, so there is no register conflict.
#
# HOOK CAVEAT: keeps the vanilla hook 0x80005D1C (TBoidLeader::perform + 8).
# BSE's kxe is a separate module and does NOT relocate vanilla .text, but if a
# future BSE build ever moves this vanilla function the hook needs in-game
# re-verification (the C2 would land on unrelated code otherwise).
def bse_boid(fps=120):
    """boid_gate wrapped in the BSE guard: fish schools + the towed Gelato red
    coin (and butterfly clouds) held at native 60 Hz, CONSTANT parity 2 on the
    director substep counter, only while BSE runs at float(G)."""
    body = [BOID_LWZ_DIRECTOR,      # lwz    r12,-0x6048(r13)
            0x280C0000,             # cmplwi r12,0
            0x41820018,             # beq +0x18: no director -> stock test
            BOID_LWZ_SUBSTEP,       # lwz    r11,0x5C(r12)
            0x71600001,             # andi.  r0,r11,1   parity 2 = 60 Hz (CONSTANT)
            0x4182000C,             # beq +0xC: even tick -> run the update
            0x70800000,             # gated: andi. r0,r4,0 -> cr0=EQ, perform's
                                    #  own beq exits via its epilogue
            0x48000008,             # b -> branch-back slot
            BOID_ORIG]              # pass/guard-fail: rlwinm. r0,r4,0,30,30
    w = _bse_guard(5 + 8, fps=fps) + body   # fail -> re-executed original (word 13)
    return _c2(BOID_HOOK, w)


# ---- Game-clock fix v15 under BSE — SELF-GATED, emitted VERBATIM ------------
# timerfix(120) already compares 0x804167B8 against float(2.0) and blr's (no-op)
# on mismatch. BSE writes exactly 2.0f every frame at FPS_120, so the self-gate
# passes there and fails at stock — no BSE guard needed. (Verified: the emitted
# body opens lis r5,0x8041 / lwz r5,0x67B8(r5) / lis r6,0x4000 / cmpw / bne blr.)
def bse_timerfix(fps=120):
    return timerfix(fps)


# ---- Raw anim-rate fixes under BSE — SELF-GATED, rate-SCALED ---------------
# Each anmrate block reads the framerate global via lfs f_,-0x3E8(r2)
# (0x804167B8) and compares it against native 0.5f; beq -> skip (stock no-op).
# Under BSE the global is 2.0f (120) / 4.0f (240), never 0.5f, so the scale
# always fires — no BSE guard needed, and the block self-disables at stock.
# (Verified: disp is -0x3E8, not the -0x3C8 60.0f slip.)
#
# THE SCALE IS 1/(2G) HERE, NOT the stock bundle's constant 1/4.  Raw rate R is
# consumed once per calc_anim, and native calc_anim is 30 Hz.  In the STOCK kit
# substep_granularity() pins calc_anim at 120 Hz at every G -> constant 30/120.
# BSE has NO substep retune: every cue runs at the render rate, so calc_anim is
# FPS Hz and the correct scale is 30/FPS = 1/(2G) — 0.25 at 120 (byte-identical
# to the shipping block) and 0.125 at 240.  Corroborated by HANDOFF-PC-240's
# "anmrate anims (Petey/Gooper ~8x)" under bare BSE at 240: 8x fast needs /8.
# Emitted as log2(FPS/30) successive `fmuls fR,fR,0.5f`, which is exact.
def bse_anmrate(fps=120, sites=None):
    n = int(fps // 30)
    assert n & (n - 1) == 0, f"FPS/30 = {n} is not a power of two"
    return anmrate(nmul=n.bit_length() - 1, sites=sites)


# The 2026-08-14 in-game A/B quarantined the BLANKET family (froze water-slide/
# bonk-star/warp anims — BSE natively compensates those consumers), but the
# Petey site 0x800955CC has the opposite verdict trail: the hand-written v16
# block at that site was IN-GAME-CONFIRMED, and HANDOFF-PC-240 observed
# "Petey/Gooper ~8x" fast under bare BSE — i.e. NOT natively compensated.
# Split it out so the boss fix ships while the freezing members stay dark.
ANMRATE_PETEY_SITE = ANMRATE_SITES[0]          # (0x800955CC, store) — ex-v16

def bse_anmrate_petey(fps=120):
    return bse_anmrate(fps, sites=[ANMRATE_PETEY_SITE])


# ---- Animal ×4 movement/duration under BSE — UNGATED, NEWLY GUARDED ---------
# animal_speed()'s blocks are unconditional [fadds f1,f1,f1; fadds; orig] and
# animal_duration()'s scale is gated only on the caller-LR range (Animal TU vs
# calc_anim callers), NOT on the framerate global. Both ship unconditionally
# with the substep retune in the stock bundle. Under BSE the retune is not
# present, so an unconditional ×4 would quadruple animal speeds at stock cadence
# — every block needs the BSE guard so it is inert unless the global holds 2.0f.
#
# Guard-fail = the block's original instruction runs exactly once, stock.
#   speed:    orig is the LAST body word; guard-fail -> that word (index 5+2).
#   duration: orig fdivs f0,f0,f1 is the FIRST body word AND r0 is LIVE across
#             the hook (0x8000AB5C sets r0=0x43300000, spilled at 0x8000AB64), so
#             the guard MUST NOT clobber r0 -> base=12,val=11,lit=12 keeps r0.
#             Layout: [guard][fdivs (orig)][b END on guard-pass? no] — the scale
#             is LR-gated, so guard-pass runs fdivs + LR test + scale, guard-fail
#             runs fdivs then jumps past the scale. fdivs executes exactly once
#             on both paths, converging on the final zero word.
def bse_animal_speed(fps=120):
    blocks = []
    for hook, orig in ANIMAL_SPEED_SITES:
        body = [_fadds(1, 1, 1), _fadds(1, 1, 1), orig]   # scale then original
        i_orig = 5 + 2                                     # guard-fail -> orig word
        blocks.append(_c2(hook, _bse_guard(i_orig, fps=fps) + body))
    return "\n".join(blocks)


def bse_animal_duration(fps=120):
    # Two run-once copies of the original fdivs so guard-pass and guard-fail
    # never share a word after diverging:
    #   guard-PASS  falls to G+0: fdivs, LR test, (scale | bge->END)
    #   guard-FAIL  bne -> TAIL: a second fdivs, then the branch-back
    # The bge (non-Animal caller on the PASS path) targets END = the zero pad,
    # skipping the TAIL fdivs so it is never double-run. r0 stays intact
    # (guard uses base=12,val=11,lit=12).
    G = 5
    body = [0xEC000824,                          # G+0: fdivs f0,f0,f1 (original, PASS)
            0x7D8802A6,                          # G+1: mflr  r12
            0x3D608001,                          # G+2: lis   r11,0x8001
            0x396B3000,                          # G+3: addi  r11,r11,0x3000
            0x7C0C5840,                          # G+4: cmplw r12,r11
            0,                                   # G+5: bge -> PAD (patched)
            _lfs(13, 2, HALF_DISP),              # G+6: f13 = 0.5f
            _fmuls(0, 0, 13),                    # G+7: f0 *= 0.5
            _fmuls(0, 0, 13),                    # G+8: f0 *= 0.25
            0,                                   # G+9: b PAD (patched, over the TAIL)
            0xEC000824]                          # G+10: TAIL fdivs (guard-FAIL copy),
                                                 #        falls onto PAD (zero word)
    i_tail = G + 10                              # guard-fail lands on the TAIL fdivs
    i_pad = G + len(body)                        # zero pad / branch-back
    body[5] = 0x40800000 | (((i_pad - (G + 5)) * 4) & 0xFFFC)          # bge  -> PAD
    body[9] = 0x48000000 | (((i_pad - (G + 9)) * 4) & 0x03FFFFFC)      # b    -> PAD
    guard = _bse_guard(i_tail, base=12, val=11, lit=12, fps=fps)  # keep r0 intact
    return _c2(ANIMAL_DURATION_HOOK, guard + body)


# ---- Poink v14 gate under BSE — UNGATED, NEWLY GUARDED ----------------------
# The POINK literal is unconditional: the first-tick block reverts to the Fly
# nerve when mid-flight and flyTimer<40, else falls to the original lfs. Its
# logic is rate-independent (flyTimer is spine-tick paced), but there is no
# reason to run it at stock cadence under BSE, so it takes the guard. Guard-fail
# -> the original lfs f1,-0x5ba0(r2) runs (stock: no early-explosion cancel).
# The mid-flight skip path uses bctr to 0x800E6000 (the fn epilogue) and never
# reaches the branch-back; guard-fail does NOT take that path — it lands on the
# re-executed original lfs, which then converges on the final zero word exactly
# as the non-flight / timer>=40 paths already do. r0/r11/r12 are dead across the
# hook (0x800E5E48 rewrites r0/r3/r4 before any read; r11/r12 untouched by the
# following code).
# ---- Bird walk accel under BSE — the ONLY animal term that needs help -------
# Aug-12 verdict (re-confirmed 2026-08-14): the stock-kit Animal x4 codes are
# WRONG under BSE — linear movement speeds self-compensate (SMSGetAnmFrameRate
# returns 0.5 at BSE-120: 1/4 per-frame x 4x frames = stock), so x4 makes
# birds "fly wayyyy too fast" / "mach 10". The one term that does NOT
# self-compensate is the SQUARED accel/decel (rate^2: 1/16 per frame x 4 =
# 1/4 overall) -> walking/marching birds accelerate visibly slow while flying
# birds look perfect. Fix: scale f1 by exactly 2 at the two accel-save sites
# only ((2*0.5)^2 = 1.0 per frame x 120 = stock 4.0 x 30). Guarded on 2.0f.
#
# CADENCE (2026-08-19): the accel-save sites run on CUE_MOVE — SUBSTEP-paced.
# With the bse_substep() 120 Hz sim pin (fps > 120) AND at plain BSE-120 the
# MOVE cadence is 120 Hz at every emitted rate, and the v11 anmrate stub pins
# SMSGetAnmFrameRate at the matching 0.5 — so the needed factor is the 120
# calibration k = 2 UNIVERSALLY ((2*0.5)^2 * 120 = stock 4.0 * 30).  An earlier
# generalization scaled k = sqrt(FPS/30) per rate (float32(sqrt 8) red-zone
# literal at 240); that assumed a 240 Hz MOVE cadence, which the substep pin
# deliberately removes — do not resurrect it while the pin ships.
BIRD_ACCEL_SITES = [
    (0x80008060, 0xFFC00890),   # execWalk moving:   rate saved for accel (fmr f30,f1)
    (0x80008094, 0xFFC00890),   # execWalk stopping: rate saved for decel (fmr f30,f1)
]

def bse_bird_accel(fps=120):
    blocks = []
    for hook, orig in BIRD_ACCEL_SITES:
        body = [_fadds(1, 1, 1), orig]       # f1 *= 2, then original fmr f30,f1
        # guard-fail -> the original fmr (stock accel); pass falls into the scale
        blocks.append(_c2(hook, _bse_guard(5 + 1, fps=fps) + body))
    return "\n".join(blocks)


def bse_shimmer(fps=120):
    """SHIMMER with its stored J3DFrameCtrl rate rescaled. TShimmer's private
    ctrl is pinned at 1.0 by init and advances once per CUE_MOVE — SUBSTEP
    cadence, 120 Hz at every emitted rate once the bse_substep() pin is in
    (and natively at 120).  Native pace is 30 Hz, so the correct stored rate
    is 30/SIM = 0.25f at EVERY rate — byte-identical to the shipping 120
    block.  The value is materialised by a bare `lis r12,hi16`, so it must
    have a zero low half — 0.25f (3E80) does.  The !=0.5f self-gate is
    unchanged and still fires under BSE at every rate."""
    val = struct.unpack(">I", struct.pack(">f", 30.0 / bse_sim_fps(fps)))[0]
    assert val & 0xFFFF == 0, f"shimmer rate needs more than a lis"
    assert SHIMMER.count("3D803E80") == 1, "SHIMMER layout changed — re-derive"
    return SHIMMER.replace("3D803E80", f"3D80{val >> 16:04X}")


def bse_poink(fps=120):
    # POINK body without the trailing handler-zero pad.  Rate-INDEPENDENT body:
    # flyTimer is spine-tick paced, so the bare `cmpwi r0,40` keeps its stock
    # meaning at every rate (see the POINK comment).  Only the guard scales.
    body = next(b for k, a, b in _iter_codes(POINK))[:-1]
    i_orig = len(body) - 1                        # the original lfs f1,-0x5ba0(r2)
    return _c2(0x800E5E44, _bse_guard(5 + i_orig, fps=fps) + body)


def bse_bluecoin(fps=120):
    """BLUECOIN recalibrated for BSE. TCoin::perform ticks on the MOVE cue —
    SUBSTEP cadence: the full render rate at plain BSE-120, and 120 Hz at
    every higher rate once the bse_substep() pin is in.  So the correct gate
    is keep 1-of-(SIM/30) = 1-of-4 at EVERY emitted rate (30/s -> native 20s
    lifetime) — the INVERSE of the stock kit's keep 3-of-4 (which was
    calibrated to its measured ~40 ticks/s). One-word change vs the stock
    block: the modulo branch flips beq->bne (%N==0 -> decrement, else hold).
    Confirmed direction by live symptom 2026-08-13: spray coins vanished ~4x
    fast under BSE with the fix off.
    Self-gates on *0x804167B8 == float(G) like the stock block — G from the
    REAL fps (4.0f at 240), only the keep ratio is sim-derived.

    Three rate-dependent words, each asserted unique before substitution:
      3CE04000  lis   r7,0x4000   -> hi16(float G)     (the ==G self-gate)
      70A50003  andi. r5,r5,3     -> mask SIM/30 - 1   (the keep ratio)
      4182000C  beq               -> 4082000C bne      (keep-1-of-N)
    """
    n = bse_sim_fps(fps) // 30
    assert n & (n - 1) == 0, f"SIM/30 = {n} is not a power of two — no andi. mask"
    out = BLUECOIN
    for old, new in (("4182000C", "4082000C"),
                     ("3CE04000", f"3CE0{bse_fps_word(fps) >> 16:04X}"),
                     ("70A50003", f"70A5{n - 1:04X}")):
        assert out.count(old) == 1, f"BLUECOIN layout changed ({old}) — re-derive"
        out = out.replace(old, new)
    return out


# ---- Shine-select cadence under BSE — PORT of select_gate, UNVERIFIED ------
# The 2026-08-19 PC playtest symptom at BSE-240: the in-stage episode/shine
# select menu RACES (way too fast) — exactly the stock-kit class-of-bug.  Under
# BSE the TSelectDir tick is UNGATED at every rate: TSelectDir::direct calls
# plain JDrama::TDirector::direct (no substep scheduler, no pad latch), so the
# menu SIM ticks at the render rate (240 Hz), while its repeat thresholds
# (N * (menu+0x14C), +0x14C = 1/SMSGetAnmFrameRate cached at 0x801744D0, and
# the pad's own 20/rate & 6/rate constants) are ticks-of-a-120Hz-menu once the
# bse_substep() ANMRATE_STUB pins the rate at 0.5f.  240 ticks/s against
# 120Hz-calibrated tick counts = 2x-fast menu.  Same fix as stock: hold the
# tick to 1-in-ceil(G/2) = 120 Hz.
#
# DOUBLE-COMPENSATION AUDIT (the quarantine lesson, resolved 2026-08-20):
# SYNC-240 flagged "BSE runtime-hooks four 60.0f loads in the TSelectDir/
# TSelectGrad TU (0x80176AA4/C40/FF4/0x80177198 -> kxe 0x804D86A8)" as a
# possible BSE-side cadence compensation.  DOL disasm + the BSE v4.0.0 source
# (src/patches/widescreen.cpp) settle it: all four sites are the SAME inlined
# `lfs f0,-0x47CC(r2)` = 0.0f — the J2D ortho box LEFT constant stored to
# +0x30 — and BSE's runtime hook is SMS_PATCH_BL -> getScreenX1f(), its
# WIDESCREEN left-edge adjust (kxe 0x804D86A8 is that trampoline, not an fps
# variable; the "60.0f" reading was a mislabel).  Pure GEOMETRY — orthogonal
# to cadence.  BSE's only other select-TU hooks are pane construction / shine
# flags / BMG names (area.cpp, extendcount.cpp) and the grad DRAW-branch
# vertex hook at 0x80175868 (PAST our join 0x80175728, and we never gate the
# draw branch).  Nothing in BSE touches the tick dispatch (0x802F7DBC), the
# repeat constants, the +0x14C reciprocal site, the grad ADVANCER (0x80175584)
# or the pad read (0x802A600C/0x802A8054) — corroborated by the symptom
# itself: a BSE-compensated menu would not race.  Verdict: NO double
# compensation; gate exactly like stock.
#
# SHAPE (the three session-8 traps all apply unchanged under BSE):
#   * gate ONLY CUE_MOVE; gated frames still testPerform with CUE_CALC_ANIM
#     (J3D shine entry) and the CUE_DRAW pass is untouched;
#   * TSelectGrad's RAW +/-2 ramp rides CALC_ANIM -> its own 1-in-2G (native
#     30 Hz) gate on the same counter, read-only;
#   * pad reads must stay phase-locked to the menu tick or 240 Hz read()
#     computes 1-frame trigger edges that land on gated MOVE frames (~half of
#     all A-presses eaten).  The stock kit extends input_latch's block for
#     this, but under BSE that C2 (@0x802A600C) belongs to the ALWAYS-ON
#     substep-pin section and this section must stay independently tickable —
#     two C2s on one hook silently last-writer-wins.  So the select pad gate
#     hooks READ()'S OWN ENTRY instead (0x802A8054, single caller: the
#     gameLoop bl @0x802A600C — DOL-scanned): TSelectDir frames failing the
#     predicted (ctr+1) % n predicate zero all 4 pads' trigger words and blr
#     out, exactly the stock latch's select-case semantics.  The director is
#     read through the gpApplication OBJECT (0x803E9700, +0x4 mDirector,
#     +0x20..0x2C mGamePads — offsets proven by the shipping input_latch
#     against gameLoop's r31 = this), so no caller register is trusted.
#
# Every block carries the _bse_guard: guard-fail (BSE not at float(G)) = stock
# behavior — MOVE fires with cue=3, the ramp advances, read() runs.  All three
# ship in ONE section (a grad/pad gate without the MOVE gate would freeze on
# the never-incremented counter; a MOVE gate without the grad strobes the
# background — the session-8 v3 regression).  At fps <= 120 nothing is
# emitted: the cadence is already 120 Hz (the select screen was always fine at
# BSE-120), matching the stock kit's G=2 no-gate.
#
# UNVERIFIED (2026-08-20): built from disasm + the stock kit's in-game-proven
# design, but NOT yet A/B'd in-game under BSE-240.  Emitted with UNVERIFIED in
# the title so switch_rate installs it UNTICKED (NEVER_ENABLE marker).
# Residual risk to eyeball in the A/B: a BSE-added CALC_ANIM consumer on the
# select screen would be a new raw advancer the stock audit never saw (the
# audited set: TSelectMenu ignores it, TSelectShineManager idempotent,
# TSelectGrad gated here, TEmitterViewObj MOVE-only).
BSE_READ_HOOK = 0x802A8054      # pad read() entry; sole caller bl @0x802A600C
BSE_READ_ORIG = 0x7C0802A6      # mflr r0 — read()'s first instruction
GP_APPLICATION = 0x803E9700     # gpApplication object (BSE us.map; gameLoop r31)

def bse_select_gate(fps=120):
    """The shine-select 120 Hz cadence port: MOVE-pass gate + grad 30 Hz gate
    + read()-entry pad gate, each BSE-guarded. None at fps <= 120."""
    g = int(fps) // 60
    n = _select_divisor(g)                    # 1-in-ceil(G/2) = 120 Hz tick
    if n is None:
        return None
    G = 5                                     # guard words
    # -- MOVE gate: the stock select_gate body behind a guard. Guard-fail ->
    # the CALL words with r4 still 3 (CUE_MOVE|CALC_ANIM, stock). r0/r11/r12/
    # cr0 dead at the hook (r0 spilled at -8, r4 is the live arg — untouched).
    gate = _rate_gate(n, ctr=11, tmp=0, tmp2=10)
    L = len(gate)
    i_call = G + 11 + L
    move = [0x819E0000,                               # lwz r12,0(r30)  this->vptr
            0x3D600000 | (SELECT_DIR_VTABLE >> 16),   # lis r11,hi(vtable)
            0x616B0000 | (SELECT_DIR_VTABLE & 0xFFFF),  # ori r11,r11,lo
            0x7C0C5800,                               # cmpw r12,r11
            0x40820000 | (((i_call - (G + 4)) * 4) & 0xFFFC),  # other dir -> CALL
            0x3D808000,                               # lis r12,0x8000
            0x80000000 | (11 << 21) | (12 << 16) | SELECT_CTR,  # lwz r11,ctr
            0x396B0001,                               # addi r11,r11,1
            0x90000000 | (11 << 21) | (12 << 16) | SELECT_CTR]  # stw r11,ctr
    move += gate                                      # cr0 <- ctr % n
    move += [0x41820008,                              # pass frame -> CALL (cue=3)
             0x38800002,                              # gated: r4 = CUE_CALC_ANIM only
             0x3D800000 | (TESTPERFORM >> 16),        # CALL: lis r12,hi
             0x618C0000 | (TESTPERFORM & 0xFFFF),     # ori r12,r12,lo
             0x7D8903A6, 0x4E800421]                  # mtctr ; bctrl testPerform
    assert move[i_call - G] == 0x3D800000 | (TESTPERFORM >> 16)
    b_move = _c2(SELECT_HOOK, _bse_guard(i_call, fps=fps) + move)
    # -- grad gate: the stock select_grad_gate with the guard INSIDE the
    # cue&2-set path (cr0 holds the cue test at the hook and must be consumed
    # by word 0 before the guard recomputes it). Guard-fail -> fall through to
    # the branch-back = ramp body runs every CALC_ANIM (stock).
    n2 = 2 * g                                        # fps/30: native 30 Hz
    gate2 = _rate_gate(n2, ctr=11, tmp=0, tmp2=10)
    L2 = len(gate2)
    i_end = 13 + L2                                   # past the last word -> ramp
    grad = [0x40820014,                               # cue&2 set -> GUARD (word 5)
            0x3D800000 | (SELECT_GRAD_JOIN >> 16),    # EXIT: lis r12,hi(join)
            0x618C0000 | (SELECT_GRAD_JOIN & 0xFFFF),   # ori r12,r12,lo
            0x7D8903A6, 0x4E800420]                   # mtctr ; bctr (skip body)
    grad += _bse_guard(i_end - 5, fps=fps)            # target rel. to guard w0
    grad += [0x3D808000,                              # lis r12,0x8000
             0x80000000 | (11 << 21) | (12 << 16) | SELECT_CTR]  # lwz r11,ctr
    grad += gate2                                     # cr0 <- ctr % 2G
    grad.append(0x40820000 | (((1 - (12 + L2)) * 4) & 0xFFFC))   # != 0 -> EXIT
    b_grad = _c2(SELECT_GRAD_HOOK, grad)              # == 0: fall to ramp body
    # -- pad gate at read()'s entry: predicted (ctr+1) % n, like the stock
    # latch's select case (read runs BEFORE direct's increment). Gated frames
    # zero mGamePads[0..3] triggers (+0x1C/+0x20) and blr past the whole read;
    # LR/CTR untouched, only r0/r11/r12/cr0 clobbered (all volatile-dead at a
    # function entry whose first insn is mflr r0; read's first cr0 use is its
    # own addic. @0x802A8068).
    gate3 = _rate_gate(n, ctr=11, tmp=0, tmp2=10)
    L3 = len(gate3)
    i_orig = 33 + L3                                  # the re-executed mflr r0
    pad = [0x3D800000 | (GP_APPLICATION >> 16),       # lis r12,hi(gpApplication)
           0x618C0000 | (GP_APPLICATION & 0xFFFF),    # ori r12,r12,lo
           0x816C0004,                                # lwz r11,4(r12)   mDirector
           0x280B0000,                                # cmplwi r11,0
           0x41820000 | (((i_orig - 9) * 4) & 0xFFFC),   # null -> read()
           0x816B0000,                                # lwz r11,0(r11)   vptr
           0x3C000000 | (SELECT_DIR_VTABLE >> 16),    # lis r0,hi(vtable)
           0x60000000 | (SELECT_DIR_VTABLE & 0xFFFF),   # ori r0,r0,lo
           0x7C0B0000,                                # cmpw r11,r0
           0x40820000 | (((i_orig - 14) * 4) & 0xFFFC),  # other dir -> read()
           0x3D608000,                                # lis r11,0x8000
           0x80000000 | (11 << 21) | (11 << 16) | SELECT_CTR,  # lwz r11,ctr
           0x396B0001]                                # addi r11,r11,1 (predicted)
    pad += gate3                                      # cr0 <- (ctr+1) % n
    pad.append(0x41820000 | (((i_orig - (18 + L3)) * 4) & 0xFFFC))  # pass -> read()
    pad.append(0x38000000)                            # li r0,0
    for off in (0x20, 0x24, 0x28, 0x2C):              # mGamePads[0..3]
        pad += [0x816C0000 | off, 0x900B001C, 0x900B0020]
    pad.append(0x4E800020)                            # blr — skip read this frame
    pad.append(BSE_READ_ORIG)                         # read(): mflr r0 (original)
    assert len(pad) + G == i_orig + 1 and pad[-1] == BSE_READ_ORIG
    b_pad = _c2(BSE_READ_HOOK, _bse_guard(i_orig, fps=fps) + pad)
    return "\n".join([b_move, b_grad, b_pad])


def bse_supported(fps):
    """(ok, reason). A rate is emittable as a BSE companion iff:
      1. FPS % 60 == 0 and G = FPS/60 >= 2      — BSE writes float(G) to the
         framerate global; every guard compares against it with a bare `lis`,
         so float(G) must have a zero low half (true for every integer G).
      2. N = FPS/30 is a POWER OF TWO           — the 30Hz-class divisors
         (noki / wipe / SE / blue-coin keep ratio) are emitted as
         `andi. rX,ctr,N-1`, and the anmrate scale is built from log2(N) exact
         halvings.  A non-power-of-two N would need _rate_gate's 4-word modulo
         form, which shifts every hand-computed target_word in the BSE
         builders, AND an anmrate divisor with no exact fmuls chain.
    That admits 120 and 240 (and 480).  It rejects 180 (N = 6), and it rejects
    the fork kxe's 280 / 320 outright: 280/60 and 320/60 are not integers, so
    280/30 = 9.33 and 320/30 = 10.67 — there is no integer frame divisor, the
    game-clock fix has no exact shift (timerfix() already returns None), and
    float(280/60) = 0x40955555 has a non-zero low half, so even the 5-word
    guard prologue cannot be built with one `lis`.  Those two rates need a
    different (reciprocal-multiply) design and are deliberately NOT emitted."""
    f = int(fps)
    if f != fps or f % 60 or f // 60 < 2:
        return False, f"{fps:g} is not an integer multiple of 60 with G >= 2"
    n = f // 30
    if n & (n - 1):
        return False, f"FPS/30 = {n} is not a power of two"
    return True, ""


def bse_sim_fps(fps):
    """The SIM (substep) rate under the BSE companion. Vanilla's TMarDirector
    scheduler integrates at 120 Hz MAX: budget = 600/int(60*G) per frame with
    a 5-per-substep cost, but the FIRST substep of every frame is
    UNCONDITIONAL in the DOL (there is no zero-substep path). 120 is therefore
    the highest rate vanilla paces correctly — at 240 the sim rode the render
    rate and the game ran exactly 2x fast (PC playtest 2026-08-19). Above 120
    the bse_substep() section pins the sim at 120 Hz (stock-kit machinery),
    so SUBSTEP-paced divisors derive from min(fps, 120) while render/audio/
    timebase-paced ones keep deriving from fps."""
    return min(int(fps), 120)


def bse_substep(fps):
    """The >120 game-speed fix: pin the SIM at 120 Hz. Three stock-kit pieces,
    all in-game proven on the stock 240 desktop kit, reused VERBATIM:

    - substep_granularity(2): numerator 1200 / quantum 10. budget =
      1200/int(60*G): 40@30, 20@60, 10@120, 5@240 against quantum 10 —
      exactly 120 Hz sim at EVERY rate — plus the zero-substep C2
      @0x80299958 that vanilla lacks (without it the unconditional first
      substep makes the sim ride the render rate -> 2x fast at 240).
    - ANMRATE_STUB (v11): SMSGetAnmFrameRate returns a hard 0.5f — the
      120 Hz-sim value, correct at every pinned rate (the stock formula
      1/G would run substep-paced anims 2x slow at 240).
    - input latch (v9 shape): at 240 only every 2nd frame runs a substep, so
      pad edges on skip frames must be latched or ~half of all presses drop
      (the G=3 lesson, confirmed in-game 2026-08-09). With budget 5 /
      quantum 10 a frame substeps iff remainder >= 5; input_latch(3)'s
      5G-10 formula lands on the same threshold 5 by arithmetic coincidence,
      and its body (TMarDirector vtable check, trigger zeroing) is exactly
      what we need — reused as-is.

    At fps <= 120 the scheduler already lands on >= 1 substep per frame and
    none of this is needed: return None."""
    if fps <= 120:
        return None
    return "\n".join([substep_granularity(2), ANMRATE_STUB, input_latch(3)])


def bse_build(fps):
    """The BSE companion bundle for `fps`. Every guarded block runs only when
    the framerate global holds exactly float(FPS/60) — 2.0f at stock BSE
    FPS_120, 4.0f at the fork kxe's FPS_240 — otherwise it falls through to
    stock behavior. The blue-coin, game-clock, anmrate and shimmer blocks
    self-gate on that same global instead of taking the guard prologue.

    Divisors are split by CADENCE CLASS (see bse_sim_fps):
      SUBSTEP-paced  (blue-coin perform, shimmer ctrl, bird accel):
        derive from bse_sim_fps(fps) — 120 at every rate once the substep
        pin is active.
      RENDER/AUDIO-paced (wipe Hx funcs, SE frame-process, menu key-repeat):
        derive from fps.
      TIMEBASE-paced (game clock — OSCheckStopwatch scales with
        EmulationSpeed): derive from G = fps/60.
      Noki: cadence class UNRESOLVED — the block is CRASHES-disabled anyway;
        re-derive when the Bianco crash is root-caused.

    Rate-DEPENDENT on the REAL fps: the guard / self-gate literal (float G),
    the render-class divisors (FPS/30 — noki [unresolved, disabled], wipe, SE
    frame-process) and the game-clock shift (G).
    Rate-INDEPENDENT once the sim is pinned: the particle parity divisor
    (CONSTANT 2 — it counts gpMarDirector+0x5C, one tick per SUBSTEP, so the
    pin makes 1-in-2 = 60 Hz JPA exact at every rate, resolving the old
    BSE_PARITY_DIVISOR open question), the blue-coin keep ratio (1-of-4), the
    shimmer stored rate (0.25f), the bird accel k (2), the Poink flyTimer<40
    threshold (spine-tick paced), and the StarFix v4 blocks.

    The Animal x4 speed / duration restores are NOT emitted (see the comment
    at their slot in `sections`): under BSE linear animal movement
    self-compensates, so the only animal term in the bundle is the bird
    walk-accel x2."""
    ok, why = bse_supported(fps)
    if not ok:
        raise SystemExit(f"--bse cannot emit {fps:g}fps: {why}.\n"
                         f"Supported: 120 (stock BSE FPS_120) and 240 (fork kxe "
                         f"FPS_240). 280/320 are NOT emittable — see bse_supported().")
    fps = int(fps)
    g, n = fps // 60, fps // 30
    nsim = bse_sim_fps(fps) // 30               # substep-class divisor: 4 always
    tag = f"BSE-{fps}"
    # Both suffixes are empty at 120 so the shipping 120 titles stay byte-stable;
    # Dolphin matches enabled codes by EXACT title, so 240 titles must differ.
    sfx = "" if fps == 120 else f" {tag}"       # " BSE-240"
    bsfx = "" if fps == 120 else f"-{fps}"      # "-240" (v6-BSE-240)
    sections = []
    if fps == 120:
        # The mFPSValue poke is STOCK-KXE ONLY. The 240/280/320 fork kxe shifts
        # its module data and 0x8051E528 is NOT mFPSValue there (catalog item
        # 36; HANDOFF-PC-240 step 4) — a blind 04 write would corrupt some
        # unrelated BSE setting. At 240 the rate is picked in BSE's own in-game
        # settings menu (and persisted to memcard) instead.
        sections.append(("$BSE Force 120 FPS", BSE_FORCE_120))
    else:
        # The game-speed fix: without it the sim rides the render rate and the
        # whole game runs fps/120 x fast (2x at 240 — PC playtest 2026-08-19).
        sections.append((f"$Substep 120Hz sim pin {tag} (granularity(2) + "
                         "anmrate stub + input latch; NEEDS-TEST)",
                         bse_substep(fps)))
    sections += [
        (f"$Particle parity {tag} (JPA 60Hz gate, guarded)", bse_parity(fps)),
        # RESOLVED 2026-08-19 late (five live autopsies): the freeze was J3D's
        # push-front inserts having no already-head check — a double entry
        # under the gate's skipped clear/rebuild passes wrote packet->next =
        # packet and the draw walked the 1-cycle forever. Fixed AT THE
        # CORRUPTION SITE by the standalone "$J3D duplicate-entry guard v1"
        # (research/codes/j3d-dup-entry-guard-v1.txt), which both launchers
        # now install+enable unconditionally. The gate is UNSAFE without that
        # guard; safe and freeze-free with it (offline in-game confirmed).
        # The v4 fin-skip resets + v5 dedupe stay (stock-faithful hardening).
        # PC fps note: the readback gating gave no measured PC/Vulkan win
        # (Video-thread-bound there); the gate earns its keep on Mac/Metal
        # (measured 39%) and for cross-machine parity.
        (f"$Noki pollution 30Hz gate {tag} v6 (safe with the J3D "
         "duplicate-entry guard — REQUIRES it enabled; NEEDS-TEST under BSE)",
         bse_noki_gate(fps) + "\n" + bse_noki_copy_gate(fps)),
        (f"$HUD StarFix v4 {tag} (guarded)", bse_starfix(fps)),
        (f"$Blue-coin lifetime v6-BSE{bsfx} (keep 1-of-{nsim}; self-gated {g:g}.0f; "
         "NEEDS-TEST ~20s)", bse_bluecoin(fps)),
        (f"$Wipe pace 30Hz gate {tag} (guarded)", bse_wipe_pace(fps)),
        (f"$SE frame-process 30Hz gate {tag} (guarded)", bse_se_frame_gate(fps)),
        # The 2026-08-27 offline perf unlock, ported: the two synchronous EFB
        # peeks are the top video-thread stall class on BOTH backends (Metal:
        # measured ~58 VPS at a 240 target; Vulkan: Bianco offline ~170 -> ~315
        # with the stock gate). Render-rate class, FPS/30 divisor.
        (f"$EFB peek 30Hz gate {tag} (guarded; NEEDS-TEST)", bse_peek_gate(fps)),
        # CALC_ANIM-class parity gate (like the JPA particle parity): CONSTANT
        # 1-in-2 on the director substep counter, NOT an fps-scaled divisor.
        # Fixes the Gelato reef red-coin fish school outrunning Mario at 120.
        (f"$Boid flocking 30Hz gate {tag} (guarded; NEEDS-TEST)", bse_boid(fps)),
        (f"$Jump-chain window x4 {tag} v2 (chain records only; NEEDS-TEST)",
         bse_jump_chain(fps)),
        (f"$Game-clock fix v15 {tag} (self-gated on {g:g}.0f; NEEDS-TEST)",
         bse_timerfix(fps)),
        # The family MINUS the Petey site (quarantined: froze water-slide/
        # bonk-star/warp anims in-game 2026-08-14 — BSE natively compensates
        # those members). Petey ships separately below.
        (f"$Raw anim-rate x{30 / fps:g} fixes {tag} (self-gated on !=0.5f; "
         "NEEDS-TEST)",
         bse_anmrate(fps, sites=ANMRATE_SITES[1:])),
        (f"$Anim-rate Petey vomit-window {tag} (ex-v16 site only; self-gated; "
         "NEEDS-TEST)", bse_anmrate_petey(fps)),
        # Animal x4 movement speed / nerve duration are DELIBERATELY absent.
        # Verdict from the Aug-12 kit chat, re-confirmed in-game 2026-08-14 and
        # codified on the Mac (launcher BASELINE_FIXES): the stock-kit x4
        # assumption is WRONG under BSE at every rate — linear speeds
        # self-compensate (SMSGetAnmFrameRate returns 1/G), so x4 = "mach 10"
        # birds.  The one term that does NOT self-compensate is the squared
        # walk accel, restored by the bird-accel block below.  The builders
        # (bse_animal_speed / bse_animal_duration) stay for the record.
        (f"$Bird walk accel x2 {tag} (guarded"
         + ("" if fps == 120 else "; NEEDS-TEST") + ")", bse_bird_accel(fps)),
        (f"$Poink premature-explosion gate v14 {tag} (guarded; NEEDS-TEST)",
         bse_poink(fps)),
        (f"$Heat-haze shimmer pace{sfx} (self-gated; active under BSE {g:g}.0f)",
         bse_shimmer(fps)),
    ]
    # Shine-select 120 Hz cadence port — fps > 120 only (None at 120: the
    # cadence is already 120 Hz there and the stock kit never gated G=2).
    # The UNVERIFIED marker keeps switch_rate from auto-enabling it (installed,
    # unticked) until the in-game menu A/B — see the bse_select_gate comment.
    sel = bse_select_gate(fps)
    if sel:
        sections.append((f"$Select-menu 120Hz gate {tag} (UNVERIFIED — do not "
                         f"enable without an in-game menu pass)", sel))
    out = []
    for title, body in sections:
        out.append(title)
        out.append(body)
    return "\n".join(out)




def emit_ini(fps, title, bundle):
    """A paste-ready GMSE01.ini fragment: [Core] speed/audio plus the code, listed
    and ticked. AudioPreservePitch fixes pitch; correct *tempo* additionally needs
    the SystemTimers.cpp audio-DMA patch in dolphin-patches/ (it scales the DMA
    period by EmulationSpeed at runtime, so one build is correct at every rate)."""
    m = fps / 60.0
    return (f"# ---- GMSE01.ini fragment for {fps:g}fps — merge into the USER ini at\n"
            f"# ~/Library/Application Support/Dolphin/GameSettings/GMSE01.ini\n"
            f"# Dolphin MUST be fully quit first: it rewrites this file on close.\n"
            f"[Core]\n"
            f"EmulationSpeed = {m:g}\n"
            f"EnableCheats = True\n"
            f"AudioPreservePitch = True\n"
            f"[Gecko]\n"
            f"{title}\n{bundle}\n"
            f"[Gecko_Enabled]\n{title}\n")


def _iter_codes(bundle):
    """Walk a bundle yielding ('C2', addr, body_words) plus ('04'|'02'|'20',
    addr, value) for writes and if-equals. E0 terminators are consumed silently."""
    words = []
    for line in bundle.splitlines():
        line = line.strip()
        if not line or line[0] in "#$":
            continue
        words.extend(line.split()[:2])
    i = 0
    while i + 1 < len(words):
        w = words[i]
        if w.startswith("C2"):
            n = int(words[i + 1], 16)
            body = [int(x, 16) for x in words[i + 2: i + 2 + 2 * n]]
            yield "C2", 0x80000000 | int(w[2:], 16), body
            i += 2 + 2 * n
        elif w.startswith("02") or w.startswith("20"):
            yield w[:2], 0x80000000 | int(w[2:], 16), int(words[i + 1], 16)
            i += 2
        elif w.startswith("E0"):
            i += 2
        else:
            yield "04", 0x80000000 | int(w[2:], 16), int(words[i + 1], 16)
            i += 2


def _implied_divisor(words, ctr):
    """Recover the 1-in-N divisor a block's gate actually encodes, straight from
    the emitted words — deliberately independent of _rate_gate so the check can
    disagree with the generator."""
    for j, w in enumerate(words):
        if (w >> 26) == 28 and ((w >> 21) & 31) == ctr:          # andi. rX,ctr,N-1
            return (w & 0xFFFF) + 1
        if (w >> 26) == 14 and not ((w >> 16) & 31) and j + 1 < len(words):
            nxt = words[j + 1]                                    # li tmp,N ; divwu _,ctr,tmp
            if (nxt >> 26) == 31 and ((nxt >> 1) & 0x3FF) == 459 and ((nxt >> 16) & 31) == ctr:
                return w & 0xFFFF
    return None


PARTICLE_HOOKS = (0x802887A8, 0x80288D30, 0x80288DEC)
SDA2 = 0x80416BA0              # r2, from __init_registers @0x8000536C
FRAMERATE_GLOBAL = 0x804167B8  # = -0x3E8(r2)

def _has_bse_guard(body, fps=120):
    """True iff `body` opens with the proven guard prologue: lwz of 0x67B8 off
    a lis 0x8041 base, then a cmpw against a lis hi16(float FPS/60) - 0x4000
    (2.0f) at 120, 0x4080 (4.0f) at 240. Tolerant of the two register
    conventions used (r3 base in the parity blocks, r12 elsewhere)."""
    lit_hi = bse_fps_word(fps) >> 16
    for j in range(len(body) - 4):
        w0, w1, w2, w3, w4 = body[j:j + 5]
        base = (w0 >> 21) & 31
        if (w0 >> 26) != 15 or (w0 & 0xFFFF) != 0x8041:          # lis rB,0x8041
            continue
        if (w1 >> 26) != 32 or ((w1 >> 16) & 31) != base or (w1 & 0xFFFF) != 0x67B8:
            continue                                             # lwz rV,0x67B8(rB)
        val = (w1 >> 21) & 31
        # w2 = lis rL,hi16(float G) ; w3 = cmpw rV,rL ; w4 = bne
        if (w2 >> 26) != 15 or (w2 & 0xFFFF) != lit_hi:
            continue
        lit = (w2 >> 21) & 31
        if (w3 >> 26) != 31 or ((w3 >> 1) & 0x3FF) != 0:         # cmp
            continue
        if ((w3 >> 16) & 31) != val or ((w3 >> 11) & 31) != lit:
            continue
        if (w4 >> 26) != 16 or (w4 & 0x03FF0000) != 0x00820000:  # bne (BO/BI = 4,2)
            continue
        return True
    return False


def _check_bse(codes, n_c2, errs, fps=120):
    """BSE companion validation: guard prologue (against float FPS/60) on every
    guarded block, divisor FPS/30 for noki/wipe/SE/blue-coin, parity and shimmer
    as emitted for this rate, the mFPSValue poke present at 120 and ABSENT
    elsewhere, and no stock 04 write to 0x804167B8 (which the guard cannot save
    from a C2 collision)."""
    fps = int(fps)
    N = fps // 30                    # render-class divisor: 4 at 120, 8 at 240
    NSIM = bse_sim_fps(fps) // 30    # substep-class divisor: 4 at every rate
    G = fps // 60                    # framerate-global multiplier

    # a0. The substep 120 Hz sim pin — MANDATORY at fps > 120 (without it the
    #     sim rides the render rate: whole game fps/120 x fast), and must be
    #     ABSENT at 120 (the scheduler already lands on 1 substep per frame;
    #     the anmrate stub would be a no-op but the latch would waste cave).
    SUBSTEP_04S = {0x8029985C: 0x386004B0,   # li    r3,1200
                   0x80299974: 0x3803FFF6,   # addi  r0,r3,-10
                   0x80299980: 0x2C00000A,   # cmpwi r0,10
                   0x802A7BD8: 0xC0228028,   # anmrate stub: lfs f1,-0x7FD8(r2)
                   0x802A7BDC: 0x4E800020}   # blr
    if fps > 120:
        for addr, want in SUBSTEP_04S.items():
            if codes.get(("04", addr)) != want:
                errs.append(f"substep pin: 04 @{addr:08X} != {want:08X} "
                            f"(granularity(2)/anmrate-stub constants)")
        zs = codes.get(("C2", 0x80299958))
        if zs is None:
            errs.append("substep pin: zero-substep C2 @0x80299958 missing — "
                        "the first substep is unconditional in the DOL, so "
                        "without this the game runs fps/120 x fast")
        elif 0x2C00000A not in zs or 0x4E800420 not in zs:
            errs.append("substep pin C2 @0x80299958: expected cmpwi acc,10 + "
                        "bctr to the direct() epilogue")
        if codes.get(("C2", 0x802A600C)) is None:
            errs.append("substep pin: input latch C2 @0x802A600C missing — "
                        "~half of all pad edges drop on skip frames without it")
    else:
        for addr in SUBSTEP_04S:
            if ("04", addr) in codes:
                errs.append(f"substep pin 04 @{addr:08X} present at {fps}fps — "
                            f"the pin is only emitted above 120")
        # The pin's C2s are the actively harmful half at <=120: the input
        # latch's thresh-5 predicate (a G=3 constant) sees an invariant-0
        # accumulator remainder when budget == quantum (120fps) and zeroes
        # every trigger edge on TMarDirector-vtable directors — the
        # 2026-08-28 BSMSO start-menu lockout.
        for addr, what in ((0x802A600C, "input latch"),
                           (0x80299958, "zero-substep")):
            if ("C2", addr) in codes:
                errs.append(f"substep pin {what} C2 @{addr:08X} present at "
                            f"{fps}fps — eats trigger edges below 240; the "
                            f"pin is only emitted above 120")

    # a. mFPSValue poke - STOCK kxe only (the 240 fork shifts its module data,
    #    so 0x8051E528 is not mFPSValue there; see bse_build).
    if fps == 120:
        if codes.get(("04", 0x8051E528)) != 0x00000002:
            errs.append("$BSE Force 120 FPS: 0451E528 00000002 missing/wrong "
                        "(mFPSValue must be 2 = FPS_120)")
    elif ("04", 0x8051E528) in codes:
        errs.append(f"04 write to 0x8051E528 present at {fps}fps: that address is "
                    f"mFPSValue only in the STOCK kxe; the fork kxe shifts module "
                    f"data, so a blind write corrupts an unrelated BSE setting")
    # The stock framerate-global 04 write must NOT appear — BSE owns 0x804167B8.
    if ("04", 0x804167B8) in codes:
        errs.append("stock 04 write to 0x804167B8 present in the BSE bundle — BSE "
                    "rewrites it every frame; drop it")

    # b. Particle parity — byte-identical to the proven live-INI blocks.
    for hook in PARTICLE_HOOKS:
        body = codes.get(("C2", hook))
        want = next(b for k, a, b in _iter_codes(
            _bse_parity_block(f"C2{hook & 0x01FFFFFF:06X}", fps).replace(
                "70600001", f"7060{BSE_PARITY_DIVISOR(fps) - 1:04X}")))
        if body != want:
            errs.append(f"BSE parity @{hook:08X}: not byte-identical to the proven "
                        f"guarded parity block for {fps}fps")
        elif not _has_bse_guard(body, fps):
            errs.append(f"BSE parity @{hook:08X}: guard prologue absent")
        pn = _implied_divisor(body, ctr=3)
        if pn != BSE_PARITY_DIVISOR(fps):
            errs.append(f"BSE parity @{hook:08X}: encodes 1-in-{pn}, expected "
                        f"1-in-{BSE_PARITY_DIVISOR(fps)}")

    # c. Noki gate + copy gate — guard on every block, divisor 4 on the gated ones.
    noki_hooks = [NOKI_OBJ_CALL[0], NOKI_DRAIN_CALL[0], NOKI_TEX_CALL[0],
                  NOKI_FIN_CALL[0]]
    for hook in noki_hooks:
        body = codes.get(("C2", hook))
        if body is None:
            errs.append(f"BSE noki block @{hook:08X} missing"); continue
        if not _has_bse_guard(body, fps):
            errs.append(f"BSE noki @{hook:08X}: guard prologue absent")
        n = _implied_divisor(body, ctr=11)
        if hook == NOKI_DRAIN_CALL[0]:
            if n is not None:
                errs.append(f"BSE noki drain @{hook:08X}: carries a divisor (must "
                            f"run every frame)")
        elif n != N:
            errs.append(f"BSE noki @{hook:08X}: encodes 1-in-{n}, expected 1-in-{N}")
        if hook == NOKI_FIN_CALL[0] and not all(wd in body for wd in NOKI_QRESET):
            errs.append(f"BSE noki fin @{hook:08X}: v4 queue-count resets absent — "
                        f"a gated fin without them re-freezes Bianco Ep.1 "
                        f"(stale stamp queue -> J3D entry() self-loop)")
    if codes.get(("C2", 0x8019B120)) is None:
        errs.append("BSE noki: dedupe @0x8019B120 MISSING — v5 requires it with "
                    "the gate (same-frame same-model double-push self-loops J3D "
                    "when the counting pass is gated; Bianco intro freeze)")
    copy = codes.get(("C2", 0x802F8CF8))
    if copy is None:
        errs.append("BSE noki copy gate @0x802F8CF8 missing")
    else:
        if not _has_bse_guard(copy, fps):
            errs.append("BSE noki copy gate @0x802F8CF8: guard prologue absent")
        if _implied_divisor(copy, ctr=11) != N:
            errs.append(f"BSE noki copy gate @0x802F8CF8: divisor != {N}")
        if copy[-2] != 0x801D002C:
            errs.append("BSE noki copy gate: last real word != orig lwz r0,0x2c(r29)")

    # d. StarFix v4 — guard on all three blocks; original re-executed as the last
    #    real word.
    for addr, i_orig in BSE_STARFIX_ORIG_WORD.items():
        body = codes.get(("C2", addr))
        if body is None:
            errs.append(f"BSE StarFix @{addr:08X} missing"); continue
        if not _has_bse_guard(body, fps):
            errs.append(f"BSE StarFix @{addr:08X}: guard prologue absent")

    # e. Blue-coin — self-gated; BSE variant must carry the INVERTED %4 branch
    # (keep 1-of-4: bne 0x4082000C), never the stock keep-3-of-4 beq.
    bc = codes.get(("C2", 0x801BE880))
    if bc is None:
        errs.append("BSE bundle: blue-coin block @0x801BE880 missing")
    else:
        if 0x4082000C not in bc:
            errs.append(f"BSE blue-coin: keep-1-of-{NSIM} bne (4082000C) absent")
        if _implied_divisor(bc, ctr=5) != NSIM:
            errs.append(f"BSE blue-coin: encodes 1-in-{_implied_divisor(bc, ctr=5)}, "
                        f"expected 1-in-{NSIM} (SIM/30 — TCoin::perform is "
                        f"MOVE-paced, 120 Hz under the substep pin)")
        if (0x3CE00000 | (bse_fps_word(fps) >> 16)) not in bc:
            errs.append(f"BSE blue-coin: self-gate literal is not lis r7,"
                        f"{bse_fps_word(fps) >> 16:04X} (float {G:g}.0f)")
        if 0x4182000C in bc:
            errs.append("BSE blue-coin: stock keep-3-of-4 beq (4182000C) present — "
                        "wrong calibration for BSE")

    # f. Wipe pace — guard on all three, divisor 4 on timer + motion.
    for hook, ctr, want_n in ((WIPE_TICK_HOOK, None, None),
                              (WIPE_TIMER_HOOK, 11, N),
                              (WIPE_MOTION_HOOK, 11, N)):
        body = codes.get(("C2", hook))
        if body is None:
            errs.append(f"BSE wipe block @{hook:08X} missing"); continue
        if not _has_bse_guard(body, fps):
            errs.append(f"BSE wipe @{hook:08X}: guard prologue absent")
        if want_n is not None and _implied_divisor(body, ctr=ctr) != want_n:
            errs.append(f"BSE wipe @{hook:08X}: divisor "
                        f"{_implied_divisor(body, ctr=ctr)} != {want_n}")
    tick = codes.get(("C2", WIPE_TICK_HOOK))
    if tick is not None and 0xD3FF0018 not in tick:
        errs.append("BSE wipe tick: re-executed original stfs f31,0x18(r31) absent")

    # g. SE frame-process gate — guard on both, divisor 4, only send stores.
    for hook, may_store in ((SE30_CHECK_HOOK, False), (SE30_SEND_HOOK, True)):
        body = codes.get(("C2", hook))
        if body is None:
            errs.append(f"BSE SE gate @{hook:08X} missing"); continue
        if not _has_bse_guard(body, fps):
            errs.append(f"BSE SE gate @{hook:08X}: guard prologue absent")
        if _implied_divisor(body, ctr=12) != N:
            errs.append(f"BSE SE gate @{hook:08X}: divisor != {N}")
        real = [w for w in body if w not in (0, NOP)]
        if not real or real[-1] != SE30_ORIG:
            errs.append(f"BSE SE gate @{hook:08X}: last real word != mflr r0")
        stores = any((w >> 26) == 36 and ((w >> 21) & 31) == 12 for w in body)
        if stores != may_store:
            errs.append(f"BSE SE gate @{hook:08X}: counter store "
                        f"{'missing' if may_store else 'present'} (send owns it)")

    # g2. EFB peek gate — guard on both, divisor FPS/30, gated path blr's with
    #     the original mflr r0 as the run-stock convergence (SE-gate contract).
    for hook in (MARIO_PEEK_HOOK, SUN_PEEK_HOOK):
        body = codes.get(("C2", hook))
        if body is None:
            errs.append(f"BSE peek gate @{hook:08X} missing — Bianco online sits "
                        f"at the ~170 pre-gate ceiling without it"); continue
        if not _has_bse_guard(body, fps):
            errs.append(f"BSE peek gate @{hook:08X}: guard prologue absent")
        if _implied_divisor(body, ctr=12) != N:
            errs.append(f"BSE peek gate @{hook:08X}: divisor != {N}")
        real = [w for w in body if w not in (0, NOP)]
        if not real or real[-1] != PEEK_ORIG:
            errs.append(f"BSE peek gate @{hook:08X}: last real word != mflr r0")

    # g2b. Boid flocking gate — GUARDED. Same CALC_ANIM-parity contract as the
    #      offline gate: reads the director substep counter, forces the cue test
    #      to EQ on gated ticks (andi. r0,r4,0), re-executes the original rlwinm.
    #      as the last real word (guard-fail convergence), and the parity is the
    #      CONSTANT 1-in-2 (andi. r0,r11,1) — NEVER an fps-scaled divisor.
    body = codes.get(("C2", BOID_HOOK))
    if body is None:
        errs.append(f"BSE boid gate @{BOID_HOOK:08X} missing — the Gelato reef "
                    f"red-coin fish school outruns Mario at BSE {fps}fps")
    else:
        if not _has_bse_guard(body, fps):
            errs.append(f"BSE boid gate @{BOID_HOOK:08X}: guard prologue absent")
        if BOID_LWZ_DIRECTOR not in body or BOID_LWZ_SUBSTEP not in body:
            errs.append(f"BSE boid gate @{BOID_HOOK:08X}: does not read the "
                        f"director substep counter (gpMarDirector+0x5C)")
        if 0x71600001 not in body:
            errs.append(f"BSE boid gate @{BOID_HOOK:08X}: parity mask andi. "
                        f"r0,r11,1 absent — cadence must be the CONSTANT 1-in-2 "
                        f"(native 60 Hz), not a G-derived divisor")
        if 0x70800000 not in body:
            errs.append(f"BSE boid gate @{BOID_HOOK:08X}: no force-fail andi. "
                        f"r0,r4,0 — gated ticks would still run the flocking update")
        real = [w for w in body if w not in (0, NOP)]
        if not real or real[-1] != BOID_ORIG:
            errs.append(f"BSE boid gate @{BOID_HOOK:08X}: last real word "
                        f"{real[-1] if real else 0:08X} != the re-executed "
                        f"original {BOID_ORIG:08X} (rlwinm. r0,r4,0,30,30)")

    # g3. Jump-chain window x4 v2 — data form only: the 20-if on the framerate
    #     global with this rate's word, three 02 halfword writes of 16*4 to the
    #     chain records, and NO v1 C2 at the shared lha (that form scaled every
    #     JumpSlipRecord and shipped the landing-stun collateral, 2026-08-28).
    if ("C2", JUMPCHAIN_HOOK) in codes:
        errs.append(f"jump-chain v1 C2 @{JUMPCHAIN_HOOK:08X} present — it "
                    f"scales ALL six JumpSlipRecords (landing/getup stun); "
                    f"v2 is data writes to the three chain records")
    if codes.get(("20", FRAMERATE_GLOBAL)) != bse_fps_word(fps):
        errs.append(f"jump-chain v2: 20-if on {FRAMERATE_GLOBAL:08X} with "
                    f"{bse_fps_word(fps):08X} (float {fps/60:g}) missing")
    for rec in JUMPCHAIN_CHAIN_RECS:
        if codes.get(("02", rec)) != JUMPCHAIN_STOCK * 4:
            errs.append(f"jump-chain v2: 02 write @{rec:08X} != "
                        f"{JUMPCHAIN_STOCK * 4:#06x} (chain record mMaxTimer x4)")

    # h. Game-clock fix v15 — SELF-GATED (no BSE guard). Assert the block reads
    #    the framerate global 0x804167B8 and compares against 2.0f, then blr's.
    tfx = codes.get(("C2", 0x80348180))
    if tfx is None:
        errs.append("BSE bundle: game-clock fix v15 @0x80348180 missing")
    else:
        # lis r5,0x8041 ; lwz r5,0x67B8(r5)
        if tfx[0] != 0x3CA08041 or tfx[1] != 0x80A567B8:
            errs.append("BSE timerfix @0x80348180: does not read the framerate "
                        "global via lis r5,0x8041 / lwz r5,0x67B8(r5)")
        if (0x3CC00000 | (bse_fps_word(fps) >> 16)) not in tfx:  # lis r6,hi16(G)
            errs.append(f"BSE timerfix @0x80348180: missing the {G:g}.0f self-gate "
                        f"literal (lis r6,{bse_fps_word(fps) >> 16:04X}) - would "
                        f"fire at the wrong rate")
        if 0x4E800020 not in tfx:            # blr (replaces the original)
            errs.append("BSE timerfix @0x80348180: missing the blr")

    # i. Raw anim-rate x0.25 — SELF-GATED. Every block must reach the framerate
    #    global through r2 at disp -0x3E8 (NOT the -0x3C8 60.0f slip) and compare
    #    against native 0.5f.
    for site, _, _ in ANMRATE_SITES:
        body = codes.get(("C2", site))
        if body is None:
            errs.append(f"BSE anmrate @{site:08X} missing"); continue
        found = False
        for w in body:
            if (w >> 26) == 48 and ((w >> 16) & 31) == 2:        # lfs frX,d(r2)
                va = SDA2 + struct.unpack(">h", struct.pack(">H", w & 0xFFFF))[0]
                found = True
                if va != FRAMERATE_GLOBAL:
                    errs.append(f"BSE anmrate @{site:08X}: lfs reads 0x{va:08X}, not "
                                f"the framerate global 0x{FRAMERATE_GLOBAL:08X} "
                                f"(the -0x3C8/-0x3E8 SDA slip)")
                break
        if not found:
            errs.append(f"BSE anmrate @{site:08X}: no framerate-global read — the "
                        f"self-gate is absent, would fire at stock")
        if not any((w >> 26) == 48 and ((w >> 16) & 31) == 2
                   and (w & 0xFFFF) == (HALF_DISP & 0xFFFF) for w in body):
            errs.append(f"BSE anmrate @{site:08X}: missing the 0.5f compare "
                        f"constant (lfs f,-0x7FD8(r2)) - self-gate incomplete")
        # The scale must be exactly log2(FPS/30) halvings = 30/FPS = 1/(2G).
        want_mul = N.bit_length() - 1
        got_mul = sum(1 for w in body
                      if (w >> 26) == 59 and ((w >> 1) & 0x1F) == 25)   # fmuls
        if got_mul != want_mul:
            errs.append(f"BSE anmrate @{site:08X}: {got_mul} fmuls, expected "
                        f"{want_mul} (scale 30/{fps} = {30 / fps:g}). Under BSE "
                        f"calc_anim runs at the RENDER rate, not the stock "
                        f"substep-pinned 120 Hz, so this scale is 1/(2G) and NOT "
                        f"the stock bundle constant 1/4")

    # j. Animal x4 speed / duration — must be ABSENT. Verdict re-confirmed
    #    2026-08-14 (codified in launcher BASELINE_FIXES): linear animal
    #    movement self-compensates under BSE; the x4 restores mean "mach 10"
    #    birds. Their presence in a bundle is a regression, not an option.
    bird_hooks = {h for h, _ in BIRD_ACCEL_SITES}
    for hook, _orig in ANIMAL_SPEED_SITES:
        if hook in bird_hooks:
            continue                # the two accel-save sites carry bird-accel now
        if codes.get(("C2", hook)) is not None:
            errs.append(f"BSE animal-speed @{hook:08X} PRESENT — never emit "
                        f"Animal x4 under BSE (mach-10 birds; 2026-08-14 verdict)")
    if codes.get(("C2", ANIMAL_DURATION_HOOK)) is not None:
        errs.append(f"BSE animal-duration @{ANIMAL_DURATION_HOOK:08X} PRESENT — "
                    f"never emit Animal x4 under BSE (2026-08-14 verdict)")

    # k. Bird walk accel — GUARDED at both accel-save sites; guard-fail lands on
    #    the re-executed `fmr f30,f1`. The scale is the 120-sim calibration
    #    k=2 (ONE fadds f1,f1,f1) at EVERY rate: the sites are CUE_MOVE-paced
    #    and the substep pin holds that cadence at 120 Hz (see BIRD_ACCEL_SITES).
    for hook, orig in BIRD_ACCEL_SITES:
        body = codes.get(("C2", hook))
        if body is None:
            errs.append(f"BSE bird-accel @{hook:08X} missing"); continue
        if not _has_bse_guard(body, fps):
            errs.append(f"BSE bird-accel @{hook:08X}: guard prologue absent")
        real = [w for w in body if w not in (0, NOP)]
        if not real or real[-1] != orig:
            errs.append(f"BSE bird-accel @{hook:08X}: last real word "
                        f"{real[-1] if real else 0:08X} != re-executed original "
                        f"fmr f30,f1 ({orig:08X})")
        if sum(1 for w in body if w == _fadds(1, 1, 1)) != 1:
            errs.append(f"BSE bird-accel @{hook:08X}: scale must be exactly one "
                        f"fadds f1,f1,f1 (k=2, the 120 Hz-sim calibration — "
                        f"MOVE cadence is pinned at 120 at every rate)")

    # l. Poink v14 — GUARDED. Guard-fail lands on the re-executed original lfs
    #    f1,-0x5ba0(r2); the mid-flight bctr epilogue path must survive intact.
    pk = codes.get(("C2", 0x800E5E44))
    if pk is None:
        errs.append("BSE bundle: Poink gate @0x800E5E44 missing")
    else:
        if not _has_bse_guard(pk, fps):
            errs.append("BSE Poink @0x800E5E44: guard prologue absent")
        real = [w for w in pk if w not in (0, NOP)]
        if not real or real[-1] != 0xC022A460:   # lfs f1,-0x5ba0(r2)
            errs.append(f"BSE Poink @0x800E5E44: last real word "
                        f"{real[-1] if real else 0:08X} != re-executed original "
                        f"lfs f1,-0x5ba0(r2) (C022A460)")
        if 0x4E800420 not in pk:                  # bctr to the epilogue
            errs.append("BSE Poink @0x800E5E44: missing the bctr to the fn epilogue "
                        "(the mid-flight explosion-cancel skip path)")
        if 0x2C000028 not in pk:                  # cmpwi r0,40 (flyTimer<40)
            errs.append("BSE Poink @0x800E5E44: missing the flyTimer<40 compare "
                        "(cmpwi r0,0x28)")

    # m. Shine-select cadence port — the three blocks ship TOGETHER at fps >
    #    120 (a grad/pad gate without the MOVE gate freezes on the dead
    #    counter; a MOVE gate without the grad strobes the background — the
    #    session-8 v3 regression) and are ABSENT at 120 (cadence already
    #    120 Hz; the stock kit never gated G=2). All three carry the guard.
    sel = codes.get(("C2", SELECT_HOOK))
    sgrad = codes.get(("C2", SELECT_GRAD_HOOK))
    spad = codes.get(("C2", BSE_READ_HOOK))
    sel_n = _select_divisor(G)
    if fps <= 120:
        for hook, b in ((SELECT_HOOK, sel), (SELECT_GRAD_HOOK, sgrad),
                        (BSE_READ_HOOK, spad)):
            if b is not None:
                errs.append(f"BSE select block @{hook:08X} present at {fps}fps — "
                            f"the select tick is already 120 Hz there (stock kit "
                            f"G=2 precedent: never gate)")
    else:
        for hook, b, what in ((SELECT_HOOK, sel, "MOVE gate"),
                              (SELECT_GRAD_HOOK, sgrad, "grad 30Hz gate"),
                              (BSE_READ_HOOK, spad, "pad read gate")):
            if b is None:
                errs.append(f"BSE select {what} @{hook:08X} missing — the three "
                            f"blocks ship together (see bse_select_gate)")
                continue
            if not _has_bse_guard(b, fps):
                errs.append(f"BSE select {what} @{hook:08X}: guard prologue absent")
        def _lisori12(body):        # lis r12,hi ; ori r12,r12,lo -> 32-bit target
            for j, w in enumerate(body[:-1]):
                if (w >> 26) == 15 and ((w >> 21) & 31) == 12:
                    nxt = body[j + 1]
                    if (nxt >> 26) == 24 and ((nxt >> 21) & 31) == 12:
                        return ((w & 0xFFFF) << 16) | (nxt & 0xFFFF)
            return None
        if sel is not None:
            if _implied_divisor(sel, ctr=11) != sel_n:
                errs.append(f"BSE select gate @{SELECT_HOOK:08X}: encodes "
                            f"1-in-{_implied_divisor(sel, ctr=11)}, expected "
                            f"1-in-{sel_n} (ceil(G/2) = 120 Hz tick)")
            if _lisori12(sel) != TESTPERFORM:
                errs.append(f"BSE select gate @{SELECT_HOOK:08X}: call target != "
                            f"TViewObj::testPerform {TESTPERFORM:08X}")
            if 0x819E0000 not in sel:
                errs.append(f"BSE select gate @{SELECT_HOOK:08X}: missing the vptr "
                            f"load lwz r12,0(r30) — would throttle every "
                            f"plain-direct director (logo/menu/movie)")
            if 0x38800002 not in sel:
                errs.append(f"BSE select gate @{SELECT_HOOK:08X}: missing `li r4,2` "
                            f"— gated frames must still testPerform with "
                            f"CUE_CALC_ANIM or the J3D shines flicker (the "
                            f"session-8 v2 regression)")
        if sgrad is not None:
            gn = _implied_divisor(sgrad, ctr=11)
            if gn != 2 * G:
                errs.append(f"BSE grad gate @{SELECT_GRAD_HOOK:08X}: encodes "
                            f"1-in-{gn}, expected 1-in-{2 * G} (2G = native 30 Hz)")
            if _lisori12(sgrad) != SELECT_GRAD_JOIN:
                errs.append(f"BSE grad gate @{SELECT_GRAD_HOOK:08X}: exit target != "
                            f"the no-CALC_ANIM join {SELECT_GRAD_JOIN:08X} — any "
                            f"other exit skips or double-runs the draw branch")
        if spad is not None:
            if _implied_divisor(spad, ctr=11) != sel_n:
                errs.append(f"BSE pad read gate @{BSE_READ_HOOK:08X}: encodes "
                            f"1-in-{_implied_divisor(spad, ctr=11)}, expected "
                            f"1-in-{sel_n} — must match the MOVE gate or trigger "
                            f"edges land off-phase")
            if (0x3D800000 | (GP_APPLICATION >> 16)) not in spad or \
                    (0x618C0000 | (GP_APPLICATION & 0xFFFF)) not in spad:
                errs.append(f"BSE pad read gate @{BSE_READ_HOOK:08X}: does not "
                            f"reach the director via the gpApplication object "
                            f"{GP_APPLICATION:08X} — caller registers must not "
                            f"be trusted at a function entry")
            if 0x4E800020 not in spad:
                errs.append(f"BSE pad read gate @{BSE_READ_HOOK:08X}: missing the "
                            f"blr (gated frames must skip the whole read)")
            if spad.count(0x900B001C) != 4 or spad.count(0x900B0020) != 4:
                errs.append(f"BSE pad read gate @{BSE_READ_HOOK:08X}: trigger "
                            f"zeroing must cover all 4 pads (+0x1C/+0x20 each) — "
                            f"stale edges would fire on the next menu tick")
            real = [w for w in spad if w not in (0, NOP)]
            if not real or real[-1] != BSE_READ_ORIG:
                errs.append(f"BSE pad read gate @{BSE_READ_HOOK:08X}: last real "
                            f"word != the re-executed original mflr r0 "
                            f"({BSE_READ_ORIG:08X})")

    # 2. Shimmer — byte-identical to research/codes/shimmer-pace-v1.txt.
    shim = codes.get(("C2", 0x8019F89C))
    want_shim = next(b for k, a, b in _iter_codes(bse_shimmer(fps)))
    if shim is None:
        errs.append("BSE bundle: shimmer block @0x8019F89C missing")
    elif shim != want_shim:
        errs.append(f"BSE shimmer @0x8019F89C: not the {30 / fps:g}f-rate block "
                    f"(shimmer-pace-v1 with its stored rate rescaled to 30/{fps})")

    return n_c2, errs


def check(bundle, fps=None, bse=False):
    """Validate a bundle three ways: C2 block structure, capstone-decodability of
    every cave word, and — when fps is given — that each rate-derived constant
    matches the framerate actually requested. bse=True switches to the BSE-120
    companion checks (guard prologue present per block, divisors 4, parity and
    shimmer byte-identical) and suppresses the stock 'missing X' assertions."""
    errs, n_c2 = [], 0
    try:
        from capstone import Cs, CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN
        md = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
    except ImportError:
        md = None
        errs.append("NOTE: capstone not installed — instruction decoding skipped")

    codes = {}
    for kind, addr, payload in _iter_codes(bundle):
        codes[(kind, addr)] = payload
        if kind != "C2":
            continue
        n_c2 += 1
        tag = f"C2 @{addr:08X}"
        if not payload:
            errs.append(f"{tag}: empty body"); continue
        if payload[-1] != 0:
            errs.append(f"{tag}: last word {payload[-1]:08X} != 00000000 — the handler "
                        f"clobbers it, so a real instruction would be destroyed")
        # Trap that crashed blue-coin v1..v4: interior padding must be nop, never a
        # second zero word (every path has to converge on the single branch-back).
        for j, w in enumerate(payload[:-1]):
            if w == 0:
                errs.append(f"{tag}: interior 00000000 at word {j} — use 60000000 (nop)")
        if md:
            body = payload[:-1]
            code = b"".join(struct.pack(">I", w) for w in body)
            got = sum(1 for _ in md.disasm(code, 0))
            if got != len(body):
                errs.append(f"{tag}: capstone decoded only {got}/{len(body)} words "
                            f"— undecodable word in the cave")

    if fps is None:
        return n_c2, errs

    if bse:
        return _check_bse(codes, n_c2, errs, fps)

    g = integer_g(fps)
    gate_g = g or 2
    want_fr = int(framerate_word(fps), 16)
    got_fr = codes.get(("04", 0x804167B8))
    if got_fr is not None and got_fr != want_fr:
        errs.append(f"framerate global: {got_fr:08X} != {want_fr:08X} (float {fps/60:g})")

    for hook in PARTICLE_HOOKS:
        body = codes.get(("C2", hook))
        if body is None:
            continue
        n = _implied_divisor(body, ctr=3)
        if n != 2:
            errs.append(f"particle gate @{hook:08X}: encodes 1-in-{n}, expected the "
                        f"CONSTANT 1-in-2 — CALC_ANIM is substep-pinned at ~120 Hz "
                        f"at every G, so 1-in-{n} runs ALL JPA at {120/(n or 1):g} Hz "
                        f"instead of 60 (the 2x-slow atom decompose at 240fps)")

    if ("04", 0x8029985C) in codes:
        for addr, want, what in ((0x8029985C, 0x38600000 | 600 * gate_g, "li r3,600G"),
                                 (0x80299974, 0x38030000 | (-5 * gate_g & 0xFFFF), "addi r0,r3,-5G"),
                                 (0x80299980, 0x2C000000 | 5 * gate_g, "cmpwi r0,5G")):
            if codes.get(("04", addr)) != want:
                errs.append(f"substep {what} @{addr:08X}: {codes[('04', addr)]:08X} != {want:08X}")

    # Noki v3: whole-perform gate and dedupe must be GONE (they batch stamps
    # and eat the M-portal ripples), the four call-site blocks present and
    # consistent, with the drain block unconditional (no divisor).
    if codes.get(("C2", 0x8019D8C8)) is not None:
        errs.append("old whole-perform Noki gate @0x8019D8C8 present — v3 gates "
                    "the counting CALL SITES; the blr design batches model "
                    "stamps and delays the M-portal impact ripples")
    noki_bodies = {h: codes.get(("C2", h)) for h, _ in
                   (NOKI_OBJ_CALL, NOKI_DRAIN_CALL, NOKI_TEX_CALL, NOKI_FIN_CALL)}
    if any(b is not None for b in noki_bodies.values()):
        want_n = int(fps // 30) if (fps % 30 == 0 and fps >= 60) else None
        for (hook, target) in (NOKI_OBJ_CALL, NOKI_DRAIN_CALL, NOKI_TEX_CALL, NOKI_FIN_CALL):
            b = noki_bodies[hook]
            if b is None:
                errs.append(f"Noki v3 block @{hook:08X} missing — all four ship together")
                continue
            if (0x618C0000 | (target & 0xFFFF)) not in b:
                errs.append(f"Noki v3 @{hook:08X}: does not call {target:08X}")
            n = _implied_divisor(b, ctr=11)
            if hook == NOKI_DRAIN_CALL[0]:
                if n is not None:
                    errs.append(f"Noki v3 drain @{hook:08X} carries a divisor — the "
                                f"stamp drain must run EVERY frame")
            elif n != want_n:
                errs.append(f"Noki v3 @{hook:08X}: encodes 1-in-{n}, expected "
                            f"1-in-{want_n} (FPS/30)")
            if hook == NOKI_FIN_CALL[0] and not all(wd in b for wd in NOKI_QRESET):
                errs.append(f"Noki fin @{hook:08X}: v4 queue-count resets absent — "
                            f"a gated fin without them freezes polluted stamping "
                            f"levels (Bianco Ep.1 J3D self-loop; see NOKI_QRESET)")
        if codes.get(("C2", 0x8019B120)) is None:
            errs.append("noki_dedupe @0x8019B120 MISSING — v5 requires it with "
                        "the gate: gated counting no longer clears the buffer "
                        "between same-frame pushes, so an undeduped same-model "
                        "double-push self-loops J3D (the Bianco Ep.1 intro "
                        "freeze, reproduced twice 2026-08-19 with v4 alone)")

    # Every anmrate block must reach the framerate global through r2, never a
    # neighbouring constant in the SDA2 pool — the -0x3C8/-0x3E8 slip read 60.0f
    # and silently divided by 120 instead of 2G.
    for site, _, _ in ANMRATE_SITES:
        body = codes.get(("C2", site))
        if body is None:
            continue
        for w in body:
            if (w >> 26) == 48 and ((w >> 16) & 31) == 2:        # lfs frX,d(r2)
                va = SDA2 + struct.unpack(">h", struct.pack(">H", w & 0xFFFF))[0]
                if va != FRAMERATE_GLOBAL:
                    errs.append(f"anmrate @{site:08X}: lfs reads 0x{va:08X}, not the "
                                f"framerate global 0x{FRAMERATE_GLOBAL:08X}")
                break

    if ("C2", 0x801BE880) in codes and g != 2:
        errs.append("blue-coin block emitted at G!=2 — it is calibrated for 120fps only")

    # Test5->Test4 swap: both fn-table words together, Test4 in both, and
    # mutually exclusive with every tile-morph block (opt, smooth, bypass) —
    # the swap makes them moot and the bypass would run Test4 FPS/30 x fast.
    swap_words = [codes.get(("04", a)) for a in (WIPE_FNTAB_ID5, WIPE_FNTAB_ID6)]
    has_swap = any(w is not None for w in swap_words)
    if has_swap:
        if None in swap_words:
            errs.append("wipe5 swap: ids 5 and 6 must BOTH be redirected")
        elif set(swap_words) != {HX_TEST4}:
            errs.append(f"wipe5 swap: fn-table words {[f'{w:08X}' for w in swap_words]}"
                        f" != Hx_Test4 0x{HX_TEST4:08X}")
        if gate_g < 3:
            errs.append("wipe5 swap emitted at G<3 — 120fps keeps stock Test5")

    # Test5 smooth pacing <-> wipe_pace id-5/6 exemption must pair exactly.
    w5count = codes.get(("04", WIPE5_COUNT_SITE))
    w5div = codes.get(("C2", WIPE5_DIV_SITE))
    wp_timer_body = codes.get(("C2", WIPE_TIMER_HOOK))
    has_bypass = wp_timer_body is not None and 0x896C43D1 in wp_timer_body
    if has_swap and (w5count is not None or w5div is not None or has_bypass
                     or ("C2", WIPE5_GRAB_HOOK) in codes):
        errs.append("wipe5 swap emitted alongside tile-morph blocks (opt/smooth/"
                    "bypass) — the swap must ship alone")
    if (w5count is not None) != (w5div is not None):
        errs.append("wipe5 smooth: count word and divisor C2 must ship together")
    if w5count is not None:
        if fps % 30 or fps < 60:
            errs.append("wipe5 smooth emitted at a non-multiple-of-30 fps")
        if w5count != (0x38000000 | 80):
            errs.append(f"wipe5 smooth count: {w5count:08X} != li r0,80 — the sim-"
                        f"clock design uses a CONSTANT 80 substeps at every fps "
                        f"(frame-scaled counts stretch when the renderer sags)")
        if not has_bypass:
            errs.append("wipe5 smooth emitted but wipe_pace timer gate has no "
                        "id-5/6 sim-clock path — Test5 would run at the 30Hz gate "
                        "against 80-substep constants (4x slow)")
        else:
            for word, what in ((0x818C005C, "substep counter load (0x5C)"),
                               (0x80000000 | (11 << 16) | WIPE5_SUBSTEP_LATCH,
                                "substep latch read"),
                               (0x28000002, "delta clamp")):
                if word not in wp_timer_body:
                    errs.append(f"wipe5 sim-clock: timer cave missing the {what}")
        if w5div is not None:
            if w5div[0] != LFS_F1_20 or w5div[:3] != [LFS_F1_20, _fadds(1, 1, 1),
                                                      _fadds(1, 1, 1)]:
                errs.append("wipe5 smooth divisor C2 must be lfs f1,20.0 doubled "
                            "twice (progress = timer/80)")
    elif has_bypass:
        errs.append("wipe_pace timer gate carries the id-5/6 sim-clock path but "
                    "wipe5 smooth constants are absent — Test5 would end 4x FAST")

    # Test5 morph-wipe optimization: all four pieces must ship together. The
    # dangerous partial is "strides doubled but grab cave absent/mangled" only
    # in the sense of visual gaps (memory safety is carried by the atomic grab
    # cave itself), but a half-emitted set means the generator broke — flag it.
    grab = codes.get(("C2", WIPE5_GRAB_HOOK))
    f22b = codes.get(("C2", 0x8017E18C))
    w5_strides = [codes.get(("04", a)) for a in (0x8017E39C, 0x8017E3D8)]
    if any(x is not None for x in (grab, f22b, *w5_strides)):
        if gate_g < 3:
            errs.append("wipe5 blocks emitted at G<3 — 120fps keeps the stock look")
        if grab is None or f22b is None or None in w5_strides:
            errs.append("wipe5 optimization partially emitted — grab cave, f22 "
                        "double and both stride words must ship together")
        else:
            if w5_strides != [0x3B5A0080, 0x3B390080]:
                errs.append(f"wipe5 strides: {[w and f'{w:08X}' for w in w5_strides]}"
                            f" != ['3B5A0080', '3B390080'] (128px tile steps)")
            for target, what in ((GX_SETTEXCOPYSRC, "GXSetTexCopySrc"),
                                 (GX_SETTEXCOPYDST, "GXSetTexCopyDst"),
                                 (WIPE5_RESUME, "resume point")):
                if (0x618C0000 | (target & 0xFFFF)) not in grab:
                    errs.append(f"wipe5 grab cave: missing lis/ori of {what} "
                                f"0x{target:08X}")
            if 0x38C00001 not in grab:
                errs.append("wipe5 grab cave: half-scale flag li r6,1 missing — "
                            "a 128x128 full-res copy would overflow the 8KB "
                            "tile buffer at 0x803F4440")
            if f22b[0] != 0xC2C2B9FC or _fadds(22, 22, 22) not in f22b:
                errs.append("wipe5 f22 block must re-exec lfs f22,-0x4604(r2) "
                            "then double it (fan offset/radius 32 -> 64)")

    # Wipe pacing gate: three blocks that only make sense together — the tick
    # (counter increment in Hx_UpdateWipe) plus the two helper gates. A missing
    # tick with either gate present would freeze the counter and, if it parks
    # on a non-pass phase, stall every wipe timer forever (transition hang).
    wp_tick = codes.get(("C2", WIPE_TICK_HOOK))
    wp_timer = codes.get(("C2", WIPE_TIMER_HOOK))
    wp_motion = codes.get(("C2", WIPE_MOTION_HOOK))
    if any(x is not None for x in (wp_tick, wp_timer, wp_motion)):
        if wp_tick is None or wp_timer is None or wp_motion is None:
            errs.append("wipe pacing gate partially emitted — tick, timer and "
                        "motion blocks must ship together (a gate without the "
                        "tick can stall every wipe timer = transition hang)")
        else:
            want_n = int(fps // 30) if fps % 30 == 0 else None
            for hook, body, what in ((WIPE_TIMER_HOOK, wp_timer, "timer"),
                                     (WIPE_MOTION_HOOK, wp_motion, "motion")):
                n = _implied_divisor(body, ctr=11)
                if n != want_n:
                    errs.append(f"wipe pacing {what} gate @{hook:08X}: encodes "
                                f"1-in-{n}, expected 1-in-{want_n} (FPS/30)")
            ctr_lwz = 0x80000000 | (11 << 21) | (12 << 16) | WIPE_CTR
            for body, what in ((wp_tick, "tick"), (wp_timer, "timer"),
                               (wp_motion, "motion")):
                if ctr_lwz not in body:
                    errs.append(f"wipe pacing {what} block does not read the "
                                f"shared frame counter 0x8000{WIPE_CTR:04X} — "
                                f"phases would diverge")
            if wp_tick[0] != 0xD3FF0018:
                errs.append("wipe pacing tick block must re-exec stfs f31,"
                            "0x18(r31) (Hx_UpdateWipe's rate store) first")
            if 0x3803FFFF not in wp_timer or 0x38030000 not in wp_timer:
                errs.append("wipe pacing timer gate must carry both the stock "
                            "decrement (addi r0,r3,-1) and the hold (r0=r3)")
            wp_real = [w for w in wp_motion if w not in (0, NOP)]
            if (0x618C0000 | (WIPE_MOTION_TAIL & 0xFFFF)) not in wp_motion \
                    or wp_real[-1] != 0xC0030000:
                errs.append("wipe pacing motion gate must bctr to the fn tail "
                            f"{WIPE_MOTION_TAIL:08X} on gated frames and end "
                            "with the original lfs f0,0(r3)")
    elif fps % 30 == 0 and fps >= 60:
        errs.append(f"wipe pacing gate MISSING at {fps:g}fps — every Hx wipe "
                    f"is frame-counted for 30fps rendering; the level-entry "
                    f"decompose/recompose runs {int(fps // 30)}x too fast")

    # Talk-initiation debounce: with the substep retune present, the stock
    # bit1 test at 0x8029A908 is starved by skip frames (impossible at G=6,
    # ~50% dropped at G=3) — the bundle must carry the bit0 retarget.
    if ("04", 0x8029985C) in codes:
        got = codes.get(("04", 0x8029A908))
        if got != TALK_INIT_WORD:
            errs.append(f"talk-init fix @0x8029A908: "
                        f"{got is not None and f'{got:08X}' or 'MISSING'} != "
                        f"{TALK_INIT_WORD:08X} — NPC dialogue cannot start on "
                        f"skip-frame-desynced ticks (impossible at 360fps)")

    # Turn-around freshness fix: with the substep retune present the pad samples
    # at ~120 Hz and yaw pursuit tracks through stick flips, so the bundle must
    # carry the delayed-face compare. Structure: the 0.5f gate, the ring index
    # rlwinm, and the constant-4 ring (a G-scaled delay here would be WRONG —
    # sim ticks are 120 Hz at every G).
    body = codes.get(("C2", TURNAROUND_HOOK))
    if body is not None:
        if body[0] != 0xA87F0096:
            errs.append(f"turnaround fix @{TURNAROUND_HOOK:08X}: first word "
                        f"{body[0]:08X} != the re-executed original lha r3,0x96(r31)")
        if 0x3C803F00 not in body:
            errs.append(f"turnaround fix @{TURNAROUND_HOOK:08X}: missing the 0.5f "
                        f"stock gate — the block would corrupt the check with the "
                        f"fps codes off")
        if 0x54800F7C not in body:
            errs.append(f"turnaround fix @{TURNAROUND_HOOK:08X}: missing the "
                        f"(ctr&3)*2 ring index — the delay must be the constant 4 "
                        f"ticks (stock 30 Hz staleness), never scaled by G")
    elif ("04", 0x8029985C) in codes:
        errs.append("turnaround freshness fix MISSING with the substep retune "
                    "present — 120 Hz pad sampling starves the skid-turn "
                    "threshold (turn-around run nearly impossible)")

    # Input pad-latch gate (v9): a frame runs a substep when remainder >= 5G-10,
    # so the gate's cmpwi must carry exactly that threshold. Its absence at G>=3
    # (with the substep retune present) is the shipped-2026-08-09 regression:
    # pad latch advances every rendered frame, sim consumes 2 of 3 -> ~1 in 3
    # edge inputs silently eaten.
    body = codes.get(("C2", 0x802A600C))
    latch_thresh = 5 * gate_g - 10
    if body is not None:
        if latch_thresh <= 0:
            errs.append(f"input latch emitted at G={gate_g} — threshold 5G-10 <= 0 "
                        f"means there are no skip frames; the block is dead cave weight")
        elif (0x2C040000 | (latch_thresh & 0xFFFF)) not in body:
            got = next((w for w in body if (w >> 16) == 0x2C04), None)
            errs.append(f"input latch @0x802A600C: threshold word "
                        f"{got and f'{got:08X}'} != cmpwi r4,{latch_thresh} "
                        f"(5G-10 at G={gate_g})")
    elif latch_thresh > 0 and ("04", 0x8029985C) in codes:
        errs.append(f"input latch MISSING at G={gate_g} with the substep retune "
                    f"present — edge inputs will drop on skip frames (the "
                    f"2026-08-09 dropped-inputs regression)")

    # Shine-select cadence gate: both halves must agree. The MOVE-pass gate
    # (C2 inside TDirector::direct) encodes 1-in-ceil(G/2) on the low-arena
    # counter, must re-target TViewObj::testPerform, and must carry the vptr
    # type check; the input-latch block must carry the TSelectDir vtable case
    # so pad reads stay phase-locked to the menu tick.
    sel_body = codes.get(("C2", SELECT_HOOK))
    latch_body = codes.get(("C2", 0x802A600C))
    sel_n = _select_divisor(gate_g)
    sel_vt_ori = 0x60A50000 | (SELECT_DIR_VTABLE & 0xFFFF)
    if sel_body is not None:
        n = _implied_divisor(sel_body, ctr=11)
        if n != sel_n:
            errs.append(f"select gate @{SELECT_HOOK:08X}: encodes 1-in-{n}, expected "
                        f"1-in-{sel_n} (ceil(G/2) at G={gate_g})")
        target = None
        for j, w in enumerate(sel_body[:-1]):
            if (w >> 26) == 15 and ((w >> 21) & 31) == 12 and j + 1 < len(sel_body):
                nxt = sel_body[j + 1]
                if (nxt >> 26) == 24 and ((nxt >> 21) & 31) == 12:
                    target = ((w & 0xFFFF) << 16) | (nxt & 0xFFFF)
        if target != TESTPERFORM:
            errs.append(f"select gate @{SELECT_HOOK:08X}: call target "
                        f"{target and f'{target:08X}'} != TViewObj::testPerform "
                        f"{TESTPERFORM:08X}")
        if 0x819E0000 not in sel_body:
            errs.append(f"select gate @{SELECT_HOOK:08X}: missing the vptr load "
                        f"lwz r12,0(r30) — without the director type check the "
                        f"gate throttles EVERY plain-direct director (logo/menu/"
                        f"movie)")
        if 0x38800002 not in sel_body:
            errs.append(f"select gate @{SELECT_HOOK:08X}: missing `li r4,2` — "
                        f"gated frames must still testPerform with CUE_CALC_ANIM "
                        f"or the J3D shines flicker translucent (draw buffers "
                        f"cleared each draw, entered only on CALC_ANIM; the "
                        f"v2 regression)")
        if latch_body is None or sel_vt_ori not in latch_body:
            errs.append(f"select gate present but the input-latch block has no "
                        f"TSelectDir case — pad repeat free-runs at render rate "
                        f"and menu edges are consumed off-phase")
        grad_body = codes.get(("C2", SELECT_GRAD_HOOK))
        if grad_body is None:
            errs.append(f"select gate present but the TSelectGrad 30Hz gate "
                        f"@{SELECT_GRAD_HOOK:08X} is missing — the background "
                        f"color-cycle runs at render rate ({2 * gate_g}x stock): "
                        f"the 'micro-flicker' regression")
        else:
            gn = _implied_divisor(grad_body, ctr=11)
            if gn != 2 * gate_g:
                errs.append(f"grad gate @{SELECT_GRAD_HOOK:08X}: encodes 1-in-{gn}, "
                            f"expected 1-in-{2 * gate_g} (2G = native 30 Hz)")
            gt = None
            for j, w in enumerate(grad_body[:-1]):
                if (w >> 26) == 15 and ((w >> 21) & 31) == 12 and j + 1 < len(grad_body):
                    nxt = grad_body[j + 1]
                    if (nxt >> 26) == 24 and ((nxt >> 21) & 31) == 12:
                        gt = ((w & 0xFFFF) << 16) | (nxt & 0xFFFF)
            if gt != SELECT_GRAD_JOIN:
                errs.append(f"grad gate @{SELECT_GRAD_HOOK:08X}: exit target "
                            f"{gt and f'{gt:08X}'} != the no-CALC_ANIM join "
                            f"{SELECT_GRAD_JOIN:08X}")
    elif latch_body is not None and sel_vt_ori in latch_body:
        errs.append(f"input latch has the TSelectDir case but the select gate "
                    f"@{SELECT_HOOK:08X} is missing — its counter never advances, "
                    f"so pad reads freeze on whatever phase the counter holds")
    elif sel_n and ("04", 0x8029985C) in codes and latch_body is not None:
        errs.append(f"shine-select gate MISSING at G={gate_g} with the substep "
                    f"retune present — the episode-select screen runs {2 * gate_g}x "
                    f"stock cadence with ~3x-fast repeat (unusable at 360fps)")

    # SE frame-process gate: divisor must be FPS/30 (rendered frames, like the
    # Noki gate), the overwritten original must be the mflr both functions
    # start with, and ONLY the send hook may store the shared counter — a
    # store in the check hook would double-count and shift the two gates onto
    # different frames.
    for hook, may_store in ((SE30_CHECK_HOOK, False), (SE30_SEND_HOOK, True)):
        body = codes.get(("C2", hook))
        if body is None:
            continue
        n, want_n = _implied_divisor(body, ctr=12), int(fps // 30)
        if n != want_n:
            errs.append(f"SE30 gate @{hook:08X}: encodes 1-in-{n}, expected 1-in-{want_n} (FPS/30)")
        real = [w for w in body if w not in (0, NOP)]
        if not real or real[-1] != SE30_ORIG:
            errs.append(f"SE30 gate @{hook:08X}: last real instruction "
                        f"{real[-1] if real else 0:08X} != mflr {SE30_ORIG:08X}")
        stores = any((w >> 26) == 36 and ((w >> 21) & 31) == 12 for w in body)
        if stores != may_store:
            errs.append(f"SE30 gate @{hook:08X}: counter store {'missing' if may_store else 'present'} "
                        f"— check reads, send owns the increment")
    # Never re-ship the superseded per-site cogwheel request gates alongside.
    for dead in (0x801DA1E8, 0x801DA860):
        if ("C2", dead) in codes:
            errs.append(f"superseded cogwheel request gate @{dead:08X} present — "
                        f"it starves the keep-alive window (60/sec chop); the SE30 "
                        f"frame gate replaces it")

    # Ricco hook slide-clank gate: keys the audio pump's frame counter with the
    # FPS/30 render-rate divisor, exits gated ticks through the function's own
    # epilogue, and re-executes the overwritten lha on pass ticks.
    body = codes.get(("C2", RICCOHOOK_HOOK))
    if body is not None:
        n, want_n = _implied_divisor(body, ctr=11), int(fps // 30) if fps % 30 == 0 else None
        if n != want_n:
            errs.append(f"ricco hook gate @{RICCOHOOK_HOOK:08X}: encodes 1-in-{n}, "
                        f"expected 1-in-{want_n} (FPS/30 = native 30/sec)")
        ctr_lwz = 0x80000000 | (11 << 21) | (12 << 16) | AUDIO_PUMP_CTR
        if ctr_lwz not in body:
            errs.append(f"ricco hook gate does not read the pump frame counter "
                        f"0x8000{AUDIO_PUMP_CTR:04X} — any other clock either "
                        f"scales with G or double-fires on adjacent frames")
        target = None
        for j, w in enumerate(body[:-1]):
            if (w >> 26) == 15 and ((w >> 21) & 31) == 12 and j + 1 < len(body):
                nxt = body[j + 1]                     # lis r12,hi ; ori r12,r12,lo
                if (nxt >> 26) == 24 and ((nxt >> 21) & 31) == 12:
                    target = ((w & 0xFFFF) << 16) | (nxt & 0xFFFF)
        if target != RICCOHOOK_SKIP:
            errs.append(f"ricco hook gate @{RICCOHOOK_HOOK:08X}: exit target "
                        f"{target and f'{target:08X}'} != the function's own "
                        f"epilogue {RICCOHOOK_SKIP:08X}")
        real = [w for w in body if w not in (0, NOP)]
        if real[-1] != RICCOHOOK_ORIG:
            errs.append(f"ricco hook gate @{RICCOHOOK_HOOK:08X}: last real word "
                        f"{real[-1]:08X} != the re-executed original "
                        f"{RICCOHOOK_ORIG:08X} (lha r0,0x7C(r29))")
    elif fps % 30 == 0 and fps >= 60 and ("C2", AUDIO_PUMP_HOOK) in codes:
        errs.append(f"ricco hook slide-clank gate MISSING at {fps:g}fps — the "
                    f"harbor clank retriggers at render rate near the cable hooks "
                    f"(the 240fps 'womp womp womp' report, 2026-08-10)")

    # Boid flocking gate: CONSTANT parity 2 on the director substep counter
    # (the JPA particle-parity cadence — native 60 Hz, NOT FPS/30: the v1
    # FPS/30 form played the school 2x slow, user-sighted 2026-08-18), forces
    # the cue test to EQ on gated ticks (so perform's own beq exits), and
    # re-executes the original rlwinm. on pass ticks.
    body = codes.get(("C2", BOID_HOOK))
    if body is not None:
        if BOID_LWZ_DIRECTOR not in body or BOID_LWZ_SUBSTEP not in body:
            errs.append(f"boid gate @{BOID_HOOK:08X}: does not read the "
                        f"director substep counter (gpMarDirector+0x5C) — any "
                        f"per-frame clock skews at G>=3 and a per-call tick "
                        f"divides the cadence by live TBoidLeader count")
        if 0x71600001 not in body:
            errs.append(f"boid gate @{BOID_HOOK:08X}: parity mask andi. "
                        f"r0,r11,1 absent — the cadence must be the CONSTANT "
                        f"1-in-2 (native 60 Hz), not a G-derived divisor")
        if 0x70800000 not in body:
            errs.append(f"boid gate @{BOID_HOOK:08X}: no force-fail "
                        f"andi. r0,r4,0 — gated ticks would fall through with "
                        f"a stale cue test and still run the flocking update")
        real = [w for w in body if w not in (0, NOP)]
        if real[-1] != BOID_ORIG:
            errs.append(f"boid gate @{BOID_HOOK:08X}: last real word "
                        f"{real[-1]:08X} != the re-executed original "
                        f"{BOID_ORIG:08X} (rlwinm. r0,r4,0,30,30)")
    elif fps >= 60:
        errs.append(f"boid flocking gate MISSING at {fps:g}fps — the flocking "
                    f"update runs per ~120 Hz CALC_ANIM tick (2x native), so "
                    f"the Gelato reef red-coin school swims and flees Mario "
                    f"too fast to catch (user-sighted 2026-08-18)")

    # Audio pump gate: SE processing must not outrun the 120 Hz substep request
    # rate. The gate hooks MSound::mainLoop's ENTRY, so the gated path must be a
    # bare blr (LR still the caller's) and the pass path must end on the
    # re-executed mflr r0.
    body = codes.get(("C2", AUDIO_PUMP_HOOK))
    if body is not None:
        n, want_n = _implied_divisor(body, ctr=11), int(fps // 30) if fps % 30 == 0 else None
        if n != want_n:
            errs.append(f"audio pump gate @{AUDIO_PUMP_HOOK:08X}: encodes 1-in-{n}, "
                        f"expected 1-in-{want_n} (FPS/30 = native 30 Hz)")
        ctr_lwz = 0x80000000 | (11 << 21) | (12 << 16) | AUDIO_PUMP_CTR
        if ctr_lwz not in body:
            errs.append(f"audio pump gate does not read its frame counter "
                        f"0x8000{AUDIO_PUMP_CTR:04X}")
        if 0x4E800020 not in body:
            errs.append("audio pump gate has no blr — gated frames would fall "
                        "through into mainLoop with r0/cr0 clobbered")
        real = [w for w in body if w not in (0, NOP)]
        if real[-1] != 0x7C0802A6:
            errs.append(f"audio pump gate: last real word {real[-1]:08X} != the "
                        f"re-executed original mflr r0 — pass frames would return "
                        f"through a stale LR save")
    elif fps % 30 == 0 and fps >= 60:
        errs.append(f"audio pump gate MISSING at {fps:g}fps — SE processing at "
                    f"render rate flicker-restarts continuous SEs, thrashes the "
                    f"64-voice pool and steal-kills every BGM note at birth "
                    f"(total music silence at 240fps)")

    # THP movie repace: movies are VI-retrace-paced with a wall-clock divisor
    # (5994), so under EmulationSpeed=G every THP plays G x fast unless the
    # divisor is scaled. The block must re-exec the stock li (its default),
    # carry the audioExist discriminator (or cutscene A/V desyncs), read the
    # framerate global through r2 (the SDA2-slip trap, same as anmrate), and
    # encode divisor 5994*G exactly.
    body = codes.get(("C2", THP_PACE_HOOK))
    if body is not None:
        if body[0] != THP_PACE_ORIG:
            errs.append(f"thp pace @{THP_PACE_HOOK:08X}: first word {body[0]:08X} "
                        f"!= the stock-default li r6,0x176A {THP_PACE_ORIG:08X}")
        if (0x88FF0000 | THP_AUDIO_EXIST_DISP) not in body:
            errs.append(f"thp pace @{THP_PACE_HOOK:08X}: audioExist discriminator "
                        f"(lbz r7,0x{THP_AUDIO_EXIST_DISP:X}(r31)) missing — "
                        f"audio-mastered cutscene THPs would slow to wall-clock "
                        f"video under G x audio = A/V desync")
        for w in body:
            if (w >> 26) == 32 and ((w >> 16) & 31) == 2:        # lwz rX,d(r2)
                va = SDA2 + struct.unpack(">h", struct.pack(">H", w & 0xFFFF))[0]
                if va != FRAMERATE_GLOBAL:
                    errs.append(f"thp pace: lwz reads 0x{va:08X}, not the framerate "
                                f"global 0x{FRAMERATE_GLOBAL:08X}")
                break
        else:
            errs.append("thp pace: no framerate-global read — the block would "
                        "repace movies even with the fps codes off")
        lis = next((w for w in body if (w >> 16) == 0x3CC0), None)
        ori = next((w for w in body if (w >> 16) == 0x60C6), None)
        want_n = 5994 * g if g else None
        got_n = (((lis & 0xFFFF) << 16) | (ori & 0xFFFF)) \
            if (lis is not None and ori is not None) else None
        if got_n != want_n:
            errs.append(f"thp pace divisor: {got_n} != {want_n} (5994*G at G={g}) — "
                        f"previews would play at the wrong rate")
    elif g:
        errs.append(f"thp pace MISSING at {fps:g}fps — THP movies are VI-retrace-"
                    f"paced, so the M-portal previews play {g}x fast (fast shimmer/"
                    f"mirage churn, {g}x JPEG decode load)")

    return n_c2, errs


def main():
    ap = argparse.ArgumentParser(description="Generate the SMS high-FPS Gecko bundle for a target framerate.")
    ap.add_argument("fps", type=float, help="target framerate (e.g. 120, 180, 240; must be a multiple of 60 for exact particle parity)")
    ap.add_argument("-o", "--out", help="write bundle to file (default: stdout)")
    ap.add_argument("--no-forceopen", action="store_true", help="v3-style: omit ForceOpen so story-locked M gates stay closed")
    ap.add_argument("--no-anmrate", action="store_true", help="omit the 15 raw anim-rate /(2G) fixes (incl. Petey, ex-v16)")
    ap.add_argument("--no-substep", action="store_true", help="omit substep granularity (stock*G); sim takes one step per frame")
    ap.add_argument("--no-audio", action="store_true", help="omit the BGM fixes (DSP voice-limiter kill + tempo guard)")
    ap.add_argument("--no-stars", action="store_true", help="omit the HUD perpetual-stars fix (v4)")
    ap.add_argument("--no-noki", action="store_true", help="omit the Noki pollution-counting gate (native 30Hz, divisor FPS/30)")
    ap.add_argument("--no-poink", action="store_true", help="omit the Poink premature-explosion gate (v14)")
    ap.add_argument("--no-bluecoin", action="store_true", help="omit the blue-coin lifetime fix (only ever emitted at 120fps)")
    ap.add_argument("--no-cogwheel", action="store_true", help="omit the SE frame-process 30Hz gate (hover/creak/tentacle repeating-SE cadence; supersedes the old per-site cogwheel gate)")
    ap.add_argument("--no-input-latch", action="store_true", help="omit the v9 pad-latch gate (pad reads locked to sim frames; confirmed in-game at 180fps 2026-08-09 — omitting it drops ~1 in 3 edge inputs at G>=3; also disables the shine-select fix, which needs the latch block)")
    ap.add_argument("--no-select", action="store_true", help="omit the shine-select screen cadence gate (episode select runs at render rate: ~3x-fast cursor repeat at 360fps)")
    ap.add_argument("--no-wipe-swap", action="store_true", help="do NOT redirect wipe ids 5/6 to Hx_Test4 at G>=3; restores the wipe5_opt+smooth 128px tile morph, which the 2026-08-11 playtest rejected (wrong-scale chunks + black slabs on the boot->plaza reveal)")
    ap.add_argument("--no-wipeopt", action="store_true", help="with --no-wipe-swap only: omit the Test5 morph-wipe EFB-copy reduction (decompose/recompose transitions run 80 EFB copies/frame and tank the framerate at G>=3)")
    ap.add_argument("--no-turnfix", action="store_true", help="omit the skid-turn stick-freshness fix (120Hz pad sampling lets yaw pursuit track through a stick flip; the turn-around run threshold then almost never trips)")
    ap.add_argument("--no-wipepace", action="store_true", help="omit the wipe pacing gate (all Hx wipes are frame-counted for 30fps rendering; without it the level-entry decompose/recompose runs FPS/30 x too fast — 55ms instead of 0.67s at 360)")
    ap.add_argument("--no-audio-pump", action="store_true", help="omit the MSound::mainLoop 30Hz gate (SE processing at render rate flicker-restarts continuous SEs, thrashes the 64-voice pool and steal-kills every BGM note at birth — total music silence at 240fps)")
    ap.add_argument("--no-thp-pace", action="store_true", help="omit the THP movie repace (movies are VI-retrace-paced, so the M-portal previews play G x fast: fast shimmer/mirage churn plus G x JPEG decode load; audio movies are untouched either way)")
    ap.add_argument("--no-riccohook", action="store_true", help="omit the Ricco hook/gondola slide-clank SE cadence gate (the harbor clank retriggers at render rate: 'womp womp womp, staticy' near the cable hooks at 240fps)")
    ap.add_argument("--no-boidfix", action="store_true", help="omit the boid flocking 30Hz gate (fish schools/butterflies take fixed-size steps per rendered frame: the Gelato reef red-coin school swims and flees Mario at FPS/30 x speed)")
    ap.add_argument("--no-shimmer", action="store_true", help="omit the heat-haze shimmer pace fix (catalog item 28; self-gated on the framerate global != native 0.5f, safe to leave on)")
    ap.add_argument("--no-peekgate", action="store_true", help="omit the EFB peek 30Hz gates (Mario occlusion GXPeekARGB + sun-flare GXPeekZ sampler at render rate; each peek is a synchronous pipeline stall on Dolphin/Metal — measured ~58 VPS at a 240 target)")
    ap.add_argument("--bse", action="store_true", help="emit the BSE companion bundle (guarded blocks for the Better Sunshine Engine online mod; fps must be 120 or 240 - see bse_supported())")
    ap.add_argument("--sun-probe", action="store_true", help="NOP the sun lens-flare EFB probe (measured no gain; breaks the flare)")
    ap.add_argument("--bare", action="store_true", help="emit hex pairs only, ready for gecko.py --code-file")
    ap.add_argument("--emit-ini", action="store_true", help="emit a full GMSE01.ini fragment ([Core] + [Gecko] + [Gecko_Enabled])")
    ap.add_argument("--check", action="store_true", help="validate structure, decodability and rate constants, then exit")
    a = ap.parse_args()

    m = a.fps / 60.0
    if a.bse:
        title = f"$SMS BSE-{int(a.fps)} companion bundle (fpspatch --bse)"
        bundle = bse_build(a.fps)
    else:
        title = f"$SMS {a.fps:g}fps bundle (fpspatch{'' if not a.no_forceopen else ', no-ForceOpen'})"
        bundle = build(a.fps, forceopen=not a.no_forceopen, anmrate_fix=not a.no_anmrate,
                       substep=not a.no_substep, audio=not a.no_audio,
                       stars=not a.no_stars, sun_probe=a.sun_probe,
                       noki=not a.no_noki, poink=not a.no_poink,
                       bluecoin=not a.no_bluecoin, cogwheel=not a.no_cogwheel,
                       input_latch_fix=not a.no_input_latch,
                       select_fix=not a.no_select, wipe_opt=not a.no_wipeopt,
                       turnfix=not a.no_turnfix, wipe_pace_fix=not a.no_wipepace,
                       audio_pump=not a.no_audio_pump, thp_pace_fix=not a.no_thp_pace,
                       riccohook=not a.no_riccohook, wipe_swap=not a.no_wipe_swap,
                       shimmer=not a.no_shimmer, boidfix=not a.no_boidfix,
                       peekgate=not a.no_peekgate)

    if a.check:
        nblocks, errs = check(bundle, a.fps, bse=a.bse)
        cave = sum(len(p) for k, _, p in _iter_codes(bundle) if k == "C2")
        print(f"{a.fps:g}fps bundle: {nblocks} C2 blocks checked "
              f"(structure + decode + rate constants)")
        print(f"  C2 cave usage: {cave} words / {cave * 4} bytes — Dolphin's cave is "
              f"small and overflow fails SILENTLY (codes just don't run). If blocks "
              f"stop taking effect, drop optional ones (--no-stars, --no-poink, "
              f"--no-bluecoin) before suspecting the code itself.")
        for e in errs:
            print("  ERROR:", e)
        print("OK" if not errs else "FAILED")
        sys.exit(0 if not errs else 1)

    if integer_g(a.fps) is None:
        print(f"# WARNING: {a.fps:g}/60 is not an integer >= 2 — the emitter and substep "
              f"gates fall back to 1-in-2 and will NOT hold 60 Hz at this rate.",
              file=sys.stderr)

    if a.bare:
        # hex pairs only — gecko.py's `add` rejects any other line
        text = bundle + "\n"
    elif a.emit_ini:
        text = emit_ini(a.fps, title, bundle)
    else:
        header = (f"# ---- paste into GameSettings/GMSE01.ini [Gecko], enable the title in "
                  f"[Gecko_Enabled] ----\n"
                  f"# ALSO set EmulationSpeed = {m:g} in BOTH Dolphin.ini and GMSE01.ini "
                  f"[Core] (per-game overrides).\n"
                  f"# framerate global 0x804167B8 = {framerate_word(a.fps)} (= float {m:g})\n")
        if a.bse:
            # the BSE bundle carries its own per-section $titles — an outer
            # title would just be an empty code to Dolphin
            text = f"{header}{bundle}\n"
        else:
            text = f"{header}{title}\n{bundle}\n"

    if a.out:
        open(a.out, "w").write(text)
        print(f"wrote {a.out}  (EmulationSpeed to set: {m:g})", file=sys.stderr)
        if a.bare:
            print(f"install with:  python3 sunshine/gecko/skill/gecko.py add "
                  f'--title "{title[1:]}" --code-file {a.out} --enable', file=sys.stderr)
            print("Dolphin MUST be fully quit first — it rewrites the INI on close.",
                  file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
