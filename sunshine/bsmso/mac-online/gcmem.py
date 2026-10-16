"""Platform dispatcher for the Dolphin memory backend.

Both backends expose an identical DolphinMem API, so callers import from here
and never care which platform they are on:

    macOS   -> macmem.DolphinMem  (Mach via the signed memhelper subprocess)
    Windows -> winmem.DolphinMem  (Win32 ReadProcessMemory/WriteProcessMemory)
    Linux   -> linuxmem.DolphinMem (mmap of Dolphin's shm RAM arena)
"""
import sys

if sys.platform == "win32":
    from winmem import DolphinMem, find_dolphin_pid
elif sys.platform.startswith("linux"):
    from linuxmem import DolphinMem, find_dolphin_pid
else:
    from macmem import DolphinMem, find_dolphin_pid

from protocol import MEM1_GUEST_BASE

__all__ = ["DolphinMem", "find_dolphin_pid", "MEM1_GUEST_BASE"]
