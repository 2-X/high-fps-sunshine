"""Host-side sampling profiler for Dolphin's Video + CPU threads.
Suspend -> GetThreadContext(Rip) -> Resume, ~50Hz per thread for DUR seconds,
then symbolize via dbghelp + our PDB."""
import ctypes, time, collections, sys
from ctypes import wintypes

DUR = 15.0
PDB_DIR = r"C:\code\high-fps-sunshine\dolphin-src\Build\x64\Release\Dolphin\bin"
EXE_DIR = r"C:\code\high-fps-sunshine\dolphin-src\Binary\x64"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
dbghelp = ctypes.WinDLL("dbghelp")

# find pid + threads
import subprocess
pid = int(subprocess.run(["powershell", "-NoProfile", "-Command",
    "(Get-Process Dolphin).Id"], capture_output=True, text=True).stdout.strip())

TH32CS_SNAPTHREAD = 0x4
class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]
k32.GetThreadDescription = ctypes.WINFUNCTYPE(
    ctypes.c_long, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p))(
    ("GetThreadDescription", k32))

THREAD_ALL = 0x1FFFFF
targets = {}
snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
te = THREADENTRY32(); te.dwSize = ctypes.sizeof(THREADENTRY32)
ok = k32.Thread32First(snap, ctypes.byref(te))
while ok:
    if te.th32OwnerProcessID == pid:
        h = k32.OpenThread(THREAD_ALL, False, te.th32ThreadID)
        if h:
            nm = ctypes.c_wchar_p()
            k32.GetThreadDescription(h, ctypes.byref(nm))
            if nm.value in ("Video thread", "CPU thread"):
                targets[nm.value] = h
            else:
                k32.CloseHandle(h)
    ok = k32.Thread32Next(snap, ctypes.byref(te))
k32.CloseHandle(snap)
print("threads:", list(targets))

# CONTEXT_AMD64 | CONTEXT_CONTROL
CTX_FLAGS = 0x100001
CTX_SIZE = 1232
OFF_FLAGS, OFF_RIP = 0x30, 0xF8

raw = ctypes.create_string_buffer(CTX_SIZE + 16)
base = (ctypes.addressof(raw) + 15) & ~15
ctx = (ctypes.c_char * CTX_SIZE).from_address(base)

k32.GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
k32.SuspendThread.argtypes = [wintypes.HANDLE]
k32.ResumeThread.argtypes = [wintypes.HANDLE]

def sample_rip(h):
    if k32.SuspendThread(h) == wintypes.DWORD(-1).value:
        return None
    try:
        ctypes.memset(base, 0, CTX_SIZE)
        ctypes.c_uint.from_address(base + OFF_FLAGS).value = CTX_FLAGS
        if not k32.GetThreadContext(h, ctypes.c_void_p(base)):
            return None
        return ctypes.c_uint64.from_address(base + OFF_RIP).value
    finally:
        k32.ResumeThread(h)

hits = {n: collections.Counter() for n in targets}
end = time.time() + DUR
n = 0
while time.time() < end:
    for name, h in targets.items():
        rip = sample_rip(h)
        if rip:
            hits[name][rip] += 1
    n += 1
    time.sleep(0.008)
print(f"{n} sample rounds")

# symbolize
hproc = k32.OpenProcess(0x0400 | 0x0010, False, pid)
dbghelp.SymSetOptions(0x2 | 0x4 | 0x10)   # UNDNAME | DEFERRED | LOAD_LINES
sympath = ctypes.c_wchar_p(PDB_DIR + ";" + EXE_DIR)
if not dbghelp.SymInitializeW(hproc, sympath, True):
    print("SymInitializeW failed", ctypes.get_last_error())

MAX_NAME = 512
class SYMBOL_INFOW(ctypes.Structure):
    _fields_ = [("SizeOfStruct", wintypes.ULONG), ("TypeIndex", wintypes.ULONG),
                ("Reserved", ctypes.c_uint64 * 2), ("Index", wintypes.ULONG),
                ("Size", wintypes.ULONG), ("ModBase", ctypes.c_uint64),
                ("Flags", wintypes.ULONG), ("Value", ctypes.c_uint64),
                ("Address", ctypes.c_uint64), ("Register", wintypes.ULONG),
                ("Scope", wintypes.ULONG), ("Tag", wintypes.ULONG),
                ("NameLen", wintypes.ULONG), ("MaxNameLen", wintypes.ULONG),
                ("Name", ctypes.c_wchar * MAX_NAME)]

def sym(addr):
    si = SYMBOL_INFOW()
    si.SizeOfStruct = 88
    si.MaxNameLen = MAX_NAME - 1
    disp = ctypes.c_uint64(0)
    if dbghelp.SymFromAddrW(hproc, ctypes.c_uint64(addr), ctypes.byref(disp),
                            ctypes.byref(si)):
        return f"{si.Name}+{disp.value:#x}"
    return f"<{addr:#x}>"

for name, ctr in hits.items():
    total = sum(ctr.values())
    print(f"\n===== {name} ({total} samples) =====")
    agg = collections.Counter()
    for rip, c in ctr.items():
        agg[sym(rip)] += c
    for s, c in agg.most_common(20):
        print(f"  {c/total*100:5.1f}%  {s}")
