"""BSMSO bridge — reads local player from Dolphin RAM and relays via network.

Locates the comm buffer, joins the server, and runs a 16 ms loop:
  - Read LocalSnapshot (BE) from comm buffer → send as UDP PlayerSnapshot (LE)
  - On SnapshotBatch callback, write each remote snapshot (BE) into RemoteSnapshots

Only targeted sub-region writes are used; the full 5494-byte buffer is never
written in one shot.  PROTOCOL.md §D.1.

CLI:
    python3 bridge.py --server HOST --name NAME [--port N]

Needs sudo (task_for_pid).
"""
import argparse
import struct
import sys
import threading
import time
from typing import Optional

from gcmem import DolphinMem, find_dolphin_pid
from netclient import NetClient, JoinError
from skins import resolve_skin, encode_model_id, skin_name, SKIN_NAMES
from protocol import (
    PlayerSnapshot,
    MAGIC,
    COMM_VERSION,
    COMM_BUFFER_SIZE,
    BRIDGE_POLL_MS,
    DEFAULT_PORT,
    COMM_LOCAL_SNAPSHOT_OFFSET,
    COMM_REMOTE_SNAPSHOTS_OFFSET,
    COMM_BRIDGE_CONTROL_OFFSET,
    COMM_ROSTER_HUD_OFFSET,
    COMM_MARIO_MODEL_IDS_OFFSET,
    BRIDGE_FLAG_CONNECTED,
    SNAPSHOT_SIZE,
    MAX_PLAYERS,
)

# Comm-buffer fields the launcher writes on connect that protocol.py does not
# name explicitly (PROTOCOL.md §A.2 / launcher SetConnected).
COMM_LOCAL_SLOT_OFFSET       = 10    # u8  — bridge announces our own slot
COMM_LOCAL_NAME_OFFSET       = 32    # 16 bytes UTF-8 NUL-padded
COMM_ROSTER_HUD_SIZE         = 202   # u16 LatestSequence + 10 × 20B events
COMM_MARIO_MODEL_IDS_SIZE    = 88    # local(8) + 10 × remote(8)
ROSTER_HUD_EVENT_CONNECTED   = 1     # RosterHudEventKind: None=0, Connected=1, Disconnected=2
ROSTER_HUD_EVENT_DISCONNECTED = 2
ROSTER_HUD_EVENT_SIZE        = 20    # Sequence u16 + Kind u8 + Slot u8 + Name[16]

# BSE runs its OWN frame clock (BetterSMS::getFrameRate) and ignores the stock
# high-fps Gecko bundle, so we drive BSE's native FPS setting directly by writing
# its mFPSValue int (enum FPSSetting::Kind).  We re-assert it when it drifts so a
# stage reload can't reset it (read-compare-write, no hammering).
#
# The FPS/aspect value ints live inside BSE's Setting objects.  On the ORIGINAL
# BSMSO kxe they were at fixed guest addresses (mFPSValue @0x8051E528,
# gAspectRatioSetting value @0x8051E4D8).  The FORKED kxe (adds FPS_240/280/320)
# relocated the module's data section, so those addresses are wrong there.  We no
# longer hardcode: locate_bse_settings() discovers the live value addresses at
# attach time by name-string + pointer scan and validates them (see below).
#
# Each Setting is a 0x28-byte object laid out as:
#   +0x00 vtable  +0x04 mName(char*)  +0x08 mValuePtr  +0x0C mIsUserEditable
#   +0x10 mEditPriority  +0x14 mValueChangedCB  +0x18..+0x20 mValueRange(int[3])
#   +0x24 the trailing int value (mFPSValue / mAspectRatioValue / mViewportValue)
# mName points to a const-char* name literal; mValuePtr points AT object+0x24.
BSE_SETTING_OBJ_SIZE   = 0x28
BSE_SETTING_NAME_OFF   = 0x04   # mName (char*) relative to object start
BSE_SETTING_VALUE_OFF  = 0x24   # trailing int value relative to object start
# Settings values are small enums (FPS 0-5, aspect 0-4).  Anything larger is a
# pointer or unrelated data, not a Setting value field.
BSE_SETTING_VALUE_MAX  = 15

# Name strings each Setting carries (must match bse-fork src/module.cpp).
BSE_FPS_NAME    = b"Frame Rate\x00"
BSE_ASPECT_NAME = b"Aspect Ratio\x00"

# FPS enum (fork: 0..5).  Original kxe only had 0..2 (30/60/120).
BSE_FPS_ENUM = {30: 0, 60: 1, 120: 2, 240: 3, 280: 4, 320: 5}
BSE_FPS_120  = 2

# BSE's native widescreen setting (gAspectRatioSetting): 0=4:3, 3=16:9 (WIDE).
# Poking this replaces the stock $Widescreen Gecko (which fights BSE every frame).
# Pair with Dolphin wideScreenHack=False to avoid double-stretch.
BSE_ASPECT_WIDE = 3

# OLD hardcoded value addresses — tried first as a fast path, but only used if
# validated by reading the owning object's name pointer (see locate_bse_settings).
BSE_OLD_FPS_VALUE_ADDR    = 0x8051E528
BSE_OLD_ASPECT_VALUE_ADDR = 0x8051E4D8

# Guest MEM1 window (64MB at 0x80000000) — bounds pointer-validity checks.
MEM1_LO = 0x80000000
MEM1_HI = 0x84000000

_MAGIC_BYTES = struct.pack(">I", MAGIC)


def _verify_comm_header(buf: bytes) -> bool:
    """Return True if buf looks like a valid comm buffer (magic + version)."""
    if len(buf) < 6:
        return False
    magic   = struct.unpack_from(">I", buf, 0)[0]
    version = struct.unpack_from(">H", buf, 4)[0]
    return magic == MAGIC and version == COMM_VERSION


def _guest_of(mem: DolphinMem, host_addr: int) -> Optional[int]:
    """Translate a host address inside MEM1 back to a guest VA, or None."""
    base = getattr(mem, "_mem1_host_base", None)
    if base is None:
        return None
    off = host_addr - base
    if 0 <= off < (MEM1_HI - MEM1_LO):
        return MEM1_LO + off
    return None


def _read_ptr(mem: DolphinMem, guest_va: int) -> Optional[int]:
    """Read a big-endian 32-bit pointer at a guest VA."""
    b = mem.read(guest_va, 4)
    if b is None or len(b) != 4:
        return None
    return struct.unpack(">I", b)[0]


def _name_at(mem: DolphinMem, name_ptr: int, expected: bytes) -> bool:
    """True if the guest string at name_ptr equals expected (incl. trailing NUL)."""
    if not (MEM1_LO <= name_ptr < MEM1_HI):
        return False
    s = mem.read(name_ptr, len(expected))
    return s == expected


def _validate_setting_value_addr(mem: DolphinMem, value_addr: int,
                                 expected_name: bytes) -> bool:
    """Given a candidate value-field address (object+0x24), confirm the owning
    Setting object's mName points to `expected_name`.
    """
    obj = value_addr - BSE_SETTING_VALUE_OFF
    if obj < MEM1_LO:
        return False
    name_ptr = _read_ptr(mem, obj + BSE_SETTING_NAME_OFF)
    if name_ptr is None:
        return False
    return _name_at(mem, name_ptr, expected_name)


def _scan_settings_by_name(mem: DolphinMem, expected_name: bytes) -> Optional[int]:
    """Locate a Setting's value-field address by name-string + pointer scan.

    1. SCAN MEM1 for the name string bytes; take its guest address `S`.
    2. SCAN MEM1 for a big-endian pointer whose value == `S` — that word is the
       Setting object's mName member (object+0x04).
    3. Derive object base = (mName addr) - 0x04, value addr = object + 0x24, and
       cross-check that mName really points to the name (guards false pointers).
    Returns the guest value-field address, or None.
    """
    host_base = getattr(mem, "_mem1_host_base", None)
    if host_base is None:
        return None
    mem1_size = MEM1_HI - MEM1_LO

    # Step 1: find the name string in MEM1 (confirm full match on each hit).
    name_guest = None
    for host_hit in mem._scan_region(host_base, mem1_size, expected_name[:4].hex()):
        if mem._raw_read(host_hit, len(expected_name)) == expected_name:
            name_guest = _guest_of(mem, host_hit)
            if name_guest is not None:
                break
    if name_guest is None:
        return None

    # Step 2: find a BE pointer to that string (the object's mName member).
    #
    # NOTE: _validate_setting_value_addr() cannot reject a false positive here --
    # it derives obj from the same hit, so it only re-checks the assumption we
    # just made and passes for ANY pointer-to-name.  MEM1 also holds pointer
    # TABLES referencing these strings, whose "value" field is another pointer.
    # Writing an enum into one of those corrupts a live mName.  So additionally
    # require the value field to look like a settings enum (a small int).
    ptr_be = struct.pack(">I", name_guest).hex()
    for host_hit in mem._scan_region(host_base, mem1_size, ptr_be):
        mname_guest = _guest_of(mem, host_hit)
        if mname_guest is None:
            continue
        obj = mname_guest - BSE_SETTING_NAME_OFF
        value_addr = obj + BSE_SETTING_VALUE_OFF
        # Step 3: re-validate via the object's own name pointer.
        if not _validate_setting_value_addr(mem, value_addr, expected_name):
            continue
        raw = mem.read(value_addr, 4)
        if raw is None:
            continue
        value = struct.unpack(">i", raw)[0]
        if 0 <= value <= BSE_SETTING_VALUE_MAX:
            return value_addr
    # Better to find nothing than to hand back a pointer table to write into.
    return None


def locate_bse_settings(mem: DolphinMem) -> dict:
    """Discover BSE Setting value-field addresses (fps, aspect) in live MEM1.

    Tries the OLD hardcoded addresses first (fast path), validating each by
    reading the owning Setting object's mName pointer and matching the expected
    name string.  If a hardcoded address is stale (fork ISO), falls back to a
    name-string + pointer scan.  Returns {"fps": addr|None, "aspect": addr|None}.
    A None entry means that setting could not be located (poke disabled for it).
    """
    result = {"fps": None, "aspect": None}

    for key, old_addr, name in (
        ("fps",    BSE_OLD_FPS_VALUE_ADDR,    BSE_FPS_NAME),
        ("aspect", BSE_OLD_ASPECT_VALUE_ADDR, BSE_ASPECT_NAME),
    ):
        # Fast path: trust the old address only if its object name checks out.
        if _validate_setting_value_addr(mem, old_addr, name):
            result[key] = old_addr
            continue
        # Fallback: name-string + pointer scan.
        result[key] = _scan_settings_by_name(mem, name)

    return result


class Bridge:
    """Reads local-player state from Dolphin, publishes to BSMSO server,
    and writes remote players back into the comm buffer.
    """

    def __init__(self, mem: DolphinMem, server: str, name: str,
                 port: int = DEFAULT_PORT, fps: int = 120,
                 aspect: int = BSE_ASPECT_WIDE, skin: str = ""):
        self._mem   = mem
        self._name  = name
        # CharacterPack model id (skins.py): 8B ASCII hex, zeros = retail.
        # Sent in the JoinRequest and written to LocalMarioModelId @1297; the
        # game loads /data/bsmso_models/<id>.arc from the disc (retail
        # fallback if the pack is missing there — see skins_install.py).
        self._model_id = encode_model_id(skin)
        self._server = server
        self._port   = port
        self._client: Optional[NetClient] = None
        self._assigned_slot: Optional[int] = None
        self._comm_guest: Optional[int] = None

        # Target FPS enum value for BSE's mFPSValue (fork: 0..5).
        self._fps_target = BSE_FPS_ENUM.get(fps, BSE_FPS_120)
        # Target aspect enum for gAspectRatioSetting (2=16:10, 3=16:9 WIDE, 4=21:9).
        self._aspect_target = aspect
        # Discovered BSE Setting value-field addresses (filled at attach).
        # None => not located; poke disabled for that setting this run.
        self._bse_fps_addr: Optional[int] = None
        self._bse_aspect_addr: Optional[int] = None
        self._bse_located = False

        # Dirty-diff state for remote snapshots (PROTOCOL.md §D.1)
        self._last_remote: dict[int, bytes] = {}
        # Dirty-diff state for RemoteMarioModelIds (@1305, stride 8): the
        # roster is re-mirrored every loop; only changed slots get written.
        self._last_remote_models: dict[int, bytes] = {}

        # Roster-HUD state: the launcher writes a "Connected" event the first
        # time each remote slot appears — this is the game's "a player joined"
        # signal that spawns the puppet actor (per-frame RemoteSnapshots only
        # move an already-spawned puppet).  PROTOCOL.md §A.5.
        self._roster_seq = 0
        self._roster_events = [bytes(ROSTER_HUD_EVENT_SIZE) for _ in range(MAX_PLAYERS)]
        self._known_slots: set[int] = set()

        self._running = False

    def _on_snapshot_batch(self, entries):
        """UDP SnapshotBatch callback — write remotes into comm buffer (BE).

        Only writes the 64-byte slot sub-region; never rewrites the whole buffer.
        PROTOCOL.md §D.1, §A.4.
        """
        for slot, seq, snap in entries:
            if slot == self._assigned_slot:
                continue  # Skip our own echo (PROTOCOL.md §C.1)
            if slot < 0 or slot >= MAX_PLAYERS:
                continue
            # Sanitize inbound anim id BEFORE it reaches the game. TMario::setAnimation
            # double-indexes gMarioAnimeData (411 entries); an AnimId >=411 from ANY
            # peer (buggy bot or malicious client) walks off the table -> wild pointer
            # -> ISI crash. Clamp out-of-range ids to a safe idle. PROTOCOL.md §A.3.
            if snap.anim_id > 410:
                snap.anim_id = 0
            # First time we see a live remote slot, announce it to the game via
            # a RosterHud "Connected" event so it spawns the puppet actor.
            if snap.connected and slot not in self._known_slots:
                self._known_slots.add(slot)
                name = self._roster_name(slot) or snap.name
                self._emit_roster_connected(slot, name)
                # Seed the slot's model id from the roster (retail zeros if
                # unknown) so the puppet spawns with the right skin; the
                # per-loop _sync_remote_model_ids keeps it current after that.
                mid = self._roster_model_id(slot)
                self._last_remote_models[slot] = mid
                self._mem.write_comm_subregion(
                    COMM_MARIO_MODEL_IDS_OFFSET + 8 + slot * 8, mid
                )
            # Pack snapshot in big-endian (comm buffer format)
            be_bytes = snap.pack_comm()
            # Override slot field in the packed bytes (BE, offset 41 = single byte)
            ba = bytearray(be_bytes)
            ba[41] = slot
            be_bytes = bytes(ba)
            # Dirty-diff: skip if unchanged
            last = self._last_remote.get(slot)
            if last == be_bytes:
                continue
            self._last_remote[slot] = be_bytes
            # Write into RemoteSnapshots[slot] at comm_offset = 112 + 64*slot
            offset = COMM_REMOTE_SNAPSHOTS_OFFSET + SNAPSHOT_SIZE * slot
            self._mem.write_comm_subregion(offset, be_bytes)

    def _roster_name(self, slot: int) -> bytes:
        """Look up a slot's name from the netclient roster (16B NUL-padded)."""
        if self._client is not None:
            for entry in self._client.roster:
                if entry.get("slot") == slot:
                    return entry.get("name", "").encode("utf-8")[:16].ljust(16, b'\x00')
        return b''

    def _roster_model_id(self, slot: int) -> bytes:
        """A slot's CharacterPack model id from the roster (8B, zeros=retail)."""
        if self._client is not None:
            for entry in self._client.roster:
                if entry.get("slot") == slot:
                    mid = entry.get("model_id") or b''
                    return bytes(mid)[:8].ljust(8, b'\x00')
        return b'\x00' * 8

    def _sync_remote_model_ids(self):
        """Mirror roster model ids into RemoteMarioModelIds (@1305, stride 8).

        The server forces a RosterSnapshot on every model change
        (MarioModelIntent handler), so the roster is authoritative; the game
        rebuilds a puppet's body when its comm id changes ("reapply requested"
        path in _BSMSO.kxe). Dirty-diffed per slot: steady state writes nothing.
        """
        if self._client is None:
            return
        for entry in self._client.roster:
            slot = entry.get("slot")
            if slot is None or slot == self._assigned_slot:
                continue
            if not (0 <= slot < MAX_PLAYERS):
                continue
            mid = bytes(entry.get("model_id") or b'')[:8].ljust(8, b'\x00')
            if self._last_remote_models.get(slot) == mid:
                continue
            self._last_remote_models[slot] = mid
            self._mem.write_comm_subregion(
                COMM_MARIO_MODEL_IDS_OFFSET + 8 + slot * 8, mid
            )

    def _emit_roster_event(self, kind: int, slot: int, name: bytes):
        """Write a RosterHud event into the comm buffer.

        CommRosterHudSync @1095 (PROTOCOL.md §A.5): u16 BE LatestSequence, then
        10 × 20B events {seq u16 BE, kind u8, slot u8, name[16]} in a ring.
        kind: ROSTER_HUD_EVENT_CONNECTED=1, ROSTER_HUD_EVENT_DISCONNECTED=2.
        """
        name16 = (bytes(name) + b'\x00' * 16)[:16]
        self._roster_seq = (self._roster_seq + 1) & 0xFFFF
        event = (struct.pack(">H", self._roster_seq)
                 + bytes([kind & 0xFF, slot & 0xFF])
                 + name16)
        idx = (self._roster_seq - 1) % MAX_PLAYERS
        self._roster_events[idx] = event
        blob = struct.pack(">H", self._roster_seq) + b''.join(self._roster_events)
        self._mem.write_comm_subregion(COMM_ROSTER_HUD_OFFSET, blob)

    def _emit_roster_connected(self, slot: int, name: bytes):
        """Write a RosterHud 'Connected' event for slot — the game's spawn cue."""
        name16 = (bytes(name) + b'\x00' * 16)[:16]
        self._emit_roster_event(ROSTER_HUD_EVENT_CONNECTED, slot, name)
        print(f"[bridge] roster: slot {slot} connected "
              f"({name16.rstrip(chr(0).encode()).decode('ascii','replace')}) — puppet cue sent")

    def _on_player_left(self, slot: int):
        """Callback from NetClient when a remote player departs.

        Zeroes the slot's 64-byte snapshot region (so the game stops rendering
        the puppet), emits a RosterHud 'Disconnected' event (the game's despawn
        cue), and clears local tracking state.  PROTOCOL.md §A.5, catalog #35a.
        """
        if slot < 0 or slot >= MAX_PLAYERS:
            return
        # Zero the snapshot region so the game stops updating the puppet.
        offset = COMM_REMOTE_SNAPSHOTS_OFFSET + SNAPSHOT_SIZE * slot
        self._mem.write_comm_subregion(offset, bytes(SNAPSHOT_SIZE))
        # Emit the 'Disconnected' roster event — the game's despawn cue.
        name = self._roster_name(slot) or b'\x00' * 16
        self._emit_roster_event(ROSTER_HUD_EVENT_DISCONNECTED, slot, name)
        # Zero the slot's model id so a later occupant starts retail.
        self._mem.write_comm_subregion(
            COMM_MARIO_MODEL_IDS_OFFSET + 8 + slot * 8, b'\x00' * 8
        )
        # Discard local tracking for this slot.
        self._known_slots.discard(slot)
        self._last_remote.pop(slot, None)
        self._last_remote_models.pop(slot, None)
        name_str = bytes(name).rstrip(b'\x00').decode('ascii', 'replace')
        print(f"[bridge] roster: slot {slot} disconnected ({name_str}) — puppet despawn cue sent")

    def _locate_comm(self) -> bool:
        """Scan for the comm buffer; cache guest address.  Returns True on success."""
        guest = self._mem.locate_comm_buffer()
        if guest is not None:
            self._comm_guest = guest
            return True
        return False

    def _locate_bse(self):
        """Discover BSE FPS/aspect Setting addresses once (cached).

        Runs the name-string + pointer scan at attach only (not per loop).  On
        total failure logs ONE warning and leaves pokes disabled for the run.
        Requires the comm buffer to have been located first (sets MEM1 base).
        """
        if self._bse_located:
            return
        self._bse_located = True
        found = locate_bse_settings(self._mem)
        self._bse_fps_addr    = found.get("fps")
        self._bse_aspect_addr = found.get("aspect")
        if self._bse_fps_addr is None and self._bse_aspect_addr is None:
            print("[bridge] WARNING: BSE settings not located — FPS/aspect pokes "
                  "disabled; set FPS in BSE's in-game menu.", file=sys.stderr)
            return
        if self._bse_fps_addr is not None:
            print(f"[bridge] BSE FPS setting (mFPSValue) @ {self._bse_fps_addr:#010x} "
                  f"-> target enum {self._fps_target}")
        else:
            print("[bridge] BSE FPS setting not located — FPS poke disabled.",
                  file=sys.stderr)
        if self._bse_aspect_addr is not None:
            print(f"[bridge] BSE aspect setting @ {self._bse_aspect_addr:#010x} "
                  f"-> target {self._aspect_target}")
        else:
            print("[bridge] BSE aspect setting not located — aspect poke disabled.",
                  file=sys.stderr)

    def _poke_bse_settings(self):
        """Re-assert BSE FPS + aspect via read-compare-write (no hammering)."""
        if self._bse_fps_addr is not None:
            cur = self._mem.read(self._bse_fps_addr, 4)
            if cur is not None and struct.unpack(">i", cur)[0] != self._fps_target:
                self._mem.write(self._bse_fps_addr, struct.pack(">i", self._fps_target))
        if self._bse_aspect_addr is not None:
            cur = self._mem.read(self._bse_aspect_addr, 4)
            if cur is not None and struct.unpack(">i", cur)[0] != self._aspect_target:
                self._mem.write(self._bse_aspect_addr, struct.pack(">i", self._aspect_target))

    def _set_bridge_connected(self):
        """Announce the bridge 'connected' state to the game module.

        Replicates the launcher's connect-time writes (PROTOCOL.md §A.2,
        launcher SetConnected): BridgeFlags.Connected, our LocalSlot, our
        LocalPlayerName, and zero-initialised RosterHud + MarioModelIds.  We do
        NOT touch game-owned fields (DolphinState@11, PlayerCount@12, WorldSync).
        """
        ctrl = self._mem.read_comm()
        if ctrl is None or len(ctrl) < 10:
            return
        # BridgeFlags.Connected (u32 BE @6), read-modify-write.
        flags = struct.unpack_from(">I", ctrl, COMM_BRIDGE_CONTROL_OFFSET)[0]
        self._mem.write_comm_subregion(
            COMM_BRIDGE_CONTROL_OFFSET,
            struct.pack(">I", flags | BRIDGE_FLAG_CONNECTED),
        )
        # LocalSlot (u8 @10) — tell the game which slot is us.
        self._mem.write_comm_subregion(
            COMM_LOCAL_SLOT_OFFSET, bytes([self._assigned_slot & 0xFF])
        )
        # LocalPlayerName (16B @32).
        self._mem.write_comm_subregion(
            COMM_LOCAL_NAME_OFFSET,
            self._name.encode("utf-8")[:15].ljust(16, b'\x00'),
        )
        # Zero-init RosterHud (@1095) and MarioModelIds (@1297) so the regions
        # are well-formed before the first roster event / puppet is written.
        self._mem.write_comm_subregion(
            COMM_ROSTER_HUD_OFFSET, bytes(COMM_ROSTER_HUD_SIZE)
        )
        self._mem.write_comm_subregion(
            COMM_MARIO_MODEL_IDS_OFFSET, bytes(COMM_MARIO_MODEL_IDS_SIZE)
        )
        # LocalMarioModelId (@1297): our skin. The game loads the pack from
        # /data/bsmso_models/<id>.arc and rebuilds Mario's body ("Local model
        # rebuild" path); zeros (retail) if --skin was not given.
        self._mem.write_comm_subregion(
            COMM_MARIO_MODEL_IDS_OFFSET, self._model_id
        )

    def run(self):
        """Main bridge loop.  Blocks until KeyboardInterrupt or fatal error."""
        # Locate comm buffer.  Retry so the user can start the bridge first and
        # then walk into a stage — the BSMSO mod only publishes the comm buffer
        # while in an active stage (not at the title screen or while paused).
        print("[bridge] Scanning for BSMSO comm buffer…")
        while not self._locate_comm():
            print("[bridge] Comm buffer not found (enter a stage — Delfino Plaza). "
                  "Retrying in 3s…", file=sys.stderr)
            time.sleep(3.0)

        print(f"[bridge] Found comm buffer at guest {self._comm_guest:#010x}")

        # Discover BSE Setting addresses now that MEM1 base is known (attach-time
        # only — never per loop).  Safe if it fails: pokes just disable.
        self._locate_bse()

        # Connect to server and join
        self._client = NetClient(
            self._server,
            port=self._port,
            model_id=self._model_id,
            on_snapshot_batch=self._on_snapshot_batch,
            on_player_left=self._on_player_left,
        )
        try:
            slot = self._client.join(self._name)
            self._assigned_slot = slot
            print(f"[bridge] Joined as slot {slot} (name={self._name})")
        except JoinError as e:
            print(f"[bridge] Join failed: {e}", file=sys.stderr)
            self._client.close()
            return

        # Signal connected to the game module
        self._set_bridge_connected()

        interval = BRIDGE_POLL_MS / 1000.0
        self._running = True
        print(f"[bridge] Running at ~{1000//BRIDGE_POLL_MS} Hz…")

        try:
            while self._running:
                t0 = time.monotonic()

                # Read comm buffer
                buf = self._mem.read_comm()
                if buf is None or not _verify_comm_header(buf):
                    # Re-resolve comm buffer on magic mismatch / read failure.
                    # A comm re-locate can mean a stage reload relocated module
                    # data, so re-run BSE discovery once after re-locating.
                    print("[bridge] Comm buffer invalid — re-scanning…")
                    if not self._locate_comm():
                        print("[bridge] Comm buffer lost. Sleeping 1s…")
                        time.sleep(1.0)
                    else:
                        self._bse_located = False
                        self._locate_bse()
                        # A relocated buffer may be fresh — re-assert our skin
                        # and drop the model-id dirty cache so remotes re-sync.
                        self._mem.write_comm_subregion(
                            COMM_MARIO_MODEL_IDS_OFFSET, self._model_id
                        )
                        self._last_remote_models.clear()
                    continue

                # Re-assert BSE's native FPS + 16:9 at the discovered addresses
                # (read-compare-write; no-op when already correct).  See notes above.
                self._poke_bse_settings()

                # Mirror roster skins into the comm block (dirty-diffed).
                self._sync_remote_model_ids()

                # Read LocalSnapshot (BE) @ comm offset 48
                snap_bytes = buf[COMM_LOCAL_SNAPSHOT_OFFSET:
                                  COMM_LOCAL_SNAPSHOT_OFFSET + SNAPSHOT_SIZE]
                snap = PlayerSnapshot.unpack_comm(snap_bytes)
                snap.slot      = self._assigned_slot
                snap.connected = 1

                # Send as UDP PlayerSnapshot (LE)
                self._client.send_snapshot(snap)

                elapsed = time.monotonic() - t0
                sleep_for = interval - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)

        except KeyboardInterrupt:
            print("\n[bridge] Shutting down…")
        finally:
            self._running = False
            if self._client:
                self._client.close()


def main():
    p = argparse.ArgumentParser(description="BSMSO bridge — connect Dolphin to the server")
    p.add_argument("--server", required=True, help="Server hostname/IP")
    p.add_argument("--name",   required=True, help="Player name (unique, ≤15 chars)")
    p.add_argument("--port",   type=int, default=DEFAULT_PORT)
    p.add_argument("--fps",    type=int, default=120,
                   choices=sorted(BSE_FPS_ENUM.keys()),
                   help="BSE native FPS to assert (maps to mFPSValue 0..5). "
                        "240/280/320 require the fork kxe. Default 120.")
    p.add_argument("--aspect", type=int, default=BSE_ASPECT_WIDE,
                   help="BSE aspect enum to assert (2=16:10 — exact for the MBP "
                        "16-inch panel, 3=16:9 WIDE, 4=21:9). Default 3.")
    p.add_argument("--skin", default="mario",
                   help=f"Character skin: {', '.join(SKIN_NAMES)}, or a raw "
                        f"8-hex CharacterPack id. Needs the pack baked into "
                        f"the ISO (skins_install.py). Default mario (retail).")
    args = p.parse_args()

    try:
        skin_id = resolve_skin(args.skin)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    pid = find_dolphin_pid()
    if pid is None:
        print("No Dolphin process found.", file=sys.stderr)
        sys.exit(1)
    print(f"[bridge] Dolphin pid={pid}")

    try:
        mem = DolphinMem(pid)
    except PermissionError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if skin_id:
        print(f"[bridge] Skin: {skin_name(skin_id)} (id {skin_id})")
    bridge = Bridge(mem, args.server, args.name, args.port, fps=args.fps,
                    aspect=args.aspect, skin=skin_id)
    bridge.run()


if __name__ == "__main__":
    main()
