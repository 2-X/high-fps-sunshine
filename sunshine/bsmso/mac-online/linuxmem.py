"""Linux Dolphin memory access via the emulator's shared-memory arena.

The Linux counterpart to macmem.py / winmem.py.  Dolphin backs all emulated
RAM with one POSIX shm object (Common/MemArenaUnix.cpp: shm_open
"/dolphin-emu.<pid>", unlinked right away, fd kept open for the process
lifetime) and lays MEM1 out at offset 0 of it (Core/HW/Memmap.cpp).  We reopen
that object through /proc/<pid>/fd/<n> and mmap it MAP_SHARED, so reads and
writes hit the live guest RAM directly.

Why not /proc/<pid>/mem or process_vm_readv: both need ptrace-attach rights,
and SteamOS ships kernel.yama.ptrace_scope=1 (descendants only).  Opening
/proc/<pid>/fd/<n> only needs ptrace READ access, which Yama leaves alone for
a same-user process.  It also works when Dolphin runs inside a Flatpak
sandbox (the magic link resolves to the file object, not a path).

"Host addresses" in this backend are offsets into the arena, biased by
_HOST_BASE so that offset 0 (the MEM1 base) is never a falsy 0.

Only the platform primitives are implemented here; the anchor logic and the
guest-VA / comm-buffer accessors are inherited from macmem.DolphinMem.

Public API is identical to macmem.py; bridge.py / set_bse_fps.py depend on it:
  DolphinMem(pid)
  .locate_comm_buffer() -> Optional[int]
  .read(guest_va, n) -> Optional[bytes]
  .write(guest_va, data) -> bool
  .read_comm() -> Optional[bytes]
  .write_comm_subregion(offset, data) -> bool
  find_dolphin_pid() -> Optional[int]
"""
import mmap
import os
import sys
import threading
import time
from typing import Optional

from macmem import DolphinMem as _BaseDolphinMem, _ANCHOR_GUEST
from protocol import MEM1_GUEST_BASE

# The emulator binary is installed/symlinked as "Dolphin" on Linux so every
# `pgrep -x Dolphin` in this repo matches it (and never the stock
# `dolphin-emu` or KDE's `dolphin` file manager).  dolphin-emu is accepted as
# a fallback for a plain upstream-named build.
_PROC_NAMES = ("Dolphin", "dolphin-emu")
_SHM_PREFIX = "/dev/shm/dolphin-emu."

_HOST_BASE = 0x100000000
_MEM1_MIN_SIZE = 0x1800000
_DISC_ID = b"GMSE01"


def _comm(pid: int) -> Optional[str]:
    try:
        with open(f"/proc/{pid}/comm") as fh:
            return fh.read().strip()
    except OSError:
        return None


def find_dolphin_pid() -> Optional[int]:
    """Return the newest running Dolphin PID, or None."""
    for name in _PROC_NAMES:
        pids = [int(d) for d in os.listdir("/proc")
                if d.isdigit() and _comm(int(d)) == name]
        if pids:
            return max(pids)
    return None


def _arena_fd_path(pid: int) -> Optional[str]:
    """/proc/<pid>/fd/<n> of the emulated-RAM shm object, or None when no game
    is booted (the arena only exists while emulation runs)."""
    fd_dir = f"/proc/{pid}/fd"
    try:
        names = os.listdir(fd_dir)
    except OSError:
        return None
    for n in names:
        path = f"{fd_dir}/{n}"
        try:
            if os.readlink(path).startswith(_SHM_PREFIX):
                return path
        except OSError:
            continue
    return None


class DolphinMem(_BaseDolphinMem):
    """Linux Dolphin memory interface.  Overrides only the platform seam."""

    def __init__(self, pid: int):
        # Deliberately does NOT call super().__init__() -- that spawns the Mach
        # memhelper subprocess.  Set every attribute the inherited methods use.
        self.pid = pid
        self._comm_host_addr: Optional[int] = None
        self._mem1_host_base: Optional[int] = None
        self._lock = threading.Lock()
        self._proc = None          # keeps the inherited close()/__del__ harmless
        self._mm: Optional[mmap.mmap] = None
        self._ino = None
        self._last_check = 0.0
        if not os.path.isdir(f"/proc/{pid}"):
            raise PermissionError(f"no such process: pid {pid}")
        self._attach()             # may legitimately find nothing pre-boot

    # ------------------------------------------------------------------
    # Arena attach -- lazy, and re-done when emulation restarts
    # ------------------------------------------------------------------

    def _attach(self) -> bool:
        """Map the current arena.  Emulation stop/start makes a new shm
        object, so a stale mapping is dropped and the new one picked up."""
        path = _arena_fd_path(self.pid)
        if path is None:
            self._detach()
            return False
        try:
            st = os.stat(path)
        except OSError:
            self._detach()
            return False
        if self._mm is not None and self._ino == (st.st_dev, st.st_ino):
            return True
        self._detach()
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError as exc:
            raise PermissionError(
                f"cannot open Dolphin's memory arena ({path}): {exc}. "
                f"Run this as the same user that launched Dolphin.") from exc
        try:
            if st.st_size < _MEM1_MIN_SIZE:
                return False
            self._mm = mmap.mmap(fd, st.st_size, mmap.MAP_SHARED,
                                 mmap.PROT_READ | mmap.PROT_WRITE)
        finally:
            os.close(fd)
        self._ino = (st.st_dev, st.st_ino)
        return True

    def _detach(self):
        if self._mm is not None:
            try:
                self._mm.close()
            except (BufferError, ValueError):
                pass
        self._mm = None
        self._ino = None

    # ------------------------------------------------------------------
    # Low-level read / write -- same signatures as the Mac backend
    # ------------------------------------------------------------------

    def _raw_read(self, host_addr: int, n: int) -> Optional[bytes]:
        """Read n bytes at a host address (arena offset + _HOST_BASE)."""
        off = host_addr - _HOST_BASE
        mm = self._mm
        try:
            if mm is None or off < 0 or off + n > len(mm):
                return None
            return mm[off:off + n]
        except ValueError:          # unmapped by a concurrent re-attach
            return None

    def _raw_write(self, host_addr: int, data: bytes) -> bool:
        """Write data at a host address.  PROTOCOL.md §D.2."""
        off = host_addr - _HOST_BASE
        mm = self._mm
        try:
            if mm is None or off < 0 or off + len(data) > len(mm):
                return False
            mm[off:off + len(data)] = data
            return True
        except ValueError:          # unmapped by a concurrent re-attach
            return False

    # ------------------------------------------------------------------
    # Region enumeration -- the arena is the only region
    # ------------------------------------------------------------------

    def _regions(self):
        """Yield (base, size) for the mapped arena (nothing before boot)."""
        if self._attach():
            yield _HOST_BASE, len(self._mm)

    def _scan_region(self, base: int, size: int, magic_hex: str):
        """Host addresses in [base, base+size) whose bytes == magic.

        Byte granularity, like winmem: bridge.py reuses this to find Setting
        name strings, which are not word-aligned.
        """
        magic = bytes.fromhex(magic_hex)
        mm = self._mm
        hits = []
        try:
            if mm is None:
                return hits
            start = max(base - _HOST_BASE, 0)
            end = min(start + size, len(mm))
            i = mm.find(magic, start, end)
            while i != -1:
                hits.append(_HOST_BASE + i)
                i = mm.find(magic, i + 1, end)
        except ValueError:          # unmapped by a concurrent re-attach
            pass
        return hits

    # ------------------------------------------------------------------
    # Comm-buffer location -- MEM1 sits at arena offset 0
    # ------------------------------------------------------------------

    def locate_comm_buffer(self) -> Optional[int]:
        """Find the BSMSO comm buffer.  PROTOCOL.md §A.1.

        Same fast path as winmem: confirm MEM1 by its "GMSE01" disc header,
        then read the anchor at its known guest offset.
        """
        if not self._attach():
            return None
        if self._raw_read(_HOST_BASE, len(_DISC_ID)) != _DISC_ID:
            return None
        host_anchor = _HOST_BASE + (_ANCHOR_GUEST - MEM1_GUEST_BASE)
        twelve = self._raw_read(host_anchor, 12)
        if twelve is None:
            return None
        parsed = self._try_parse_anchor(host_anchor, twelve, 0)
        if parsed is None:
            return None
        host_comm, buffer_guest = parsed
        if not self._looks_like_comm_buffer(host_comm):
            return None
        self._comm_host_addr = host_comm
        self._mem1_host_base = _HOST_BASE
        return int(buffer_guest)

    def read_comm(self) -> Optional[bytes]:
        """Read the comm buffer, noticing a stopped / restarted emulation.

        Our mapping keeps the old shm object alive after Dolphin drops it, so
        a stale arena would read back as a perfectly valid, frozen buffer.
        Re-check the live fd about once a second; on a change, forget the comm
        address so the caller re-locates against the new arena.
        """
        now = time.monotonic()
        if now - self._last_check > 1.0:
            self._last_check = now
            ino = self._ino
            if not self._attach() or self._ino != ino:
                self._comm_host_addr = None
                return None
        return super().read_comm()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Unmap the arena.  Idempotent."""
        self._detach()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    verify_write = "--verify-write" in sys.argv

    pid = find_dolphin_pid()
    if pid is None:
        print("Dolphin is not running.")
        sys.exit(1)
    print(f"Dolphin pid      : {pid}")

    try:
        mem = DolphinMem(pid)
    except PermissionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)

    regions = list(mem._regions())
    if not regions:
        print("No memory arena -- emulation is not running (boot a game).")
        sys.exit(1)
    print(f"arena size       : 0x{regions[0][1]:x}")
    print(f"disc id          : {mem._raw_read(_HOST_BASE, 6)!r}")

    guest = mem.locate_comm_buffer()
    if guest is None:
        print("Comm buffer NOT FOUND -- you are probably not in a stage "
              "(title screen / paused), or this is not the BSMSO disc.")
        sys.exit(1)

    print(f"comm buffer guest: 0x{guest:08x}")

    if verify_write:
        # No-op round trip: read 8 bytes and write the SAME bytes back, proving
        # the write path works without changing any game state.
        before = mem._raw_read(mem._comm_host_addr, 8)
        if before is None:
            print("FAIL: could not read the comm buffer")
            sys.exit(1)
        if not mem._raw_write(mem._comm_host_addr, before):
            print("FAIL: write into the arena was rejected")
            sys.exit(1)
        after = mem._raw_read(mem._comm_host_addr, 8)
        if after != before:
            print(f"FAIL: readback mismatch {before.hex()} -> {after.hex()}")
            sys.exit(1)
        print(f"write verified   : no-op round trip OK ({before.hex()})")

    mem.close()
    print("OK")
