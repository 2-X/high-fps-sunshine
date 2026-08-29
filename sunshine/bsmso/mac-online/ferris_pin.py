#!/usr/bin/env python3
"""Live test harness for the Pinna Ep5 runaway ferris wheel high-fps bug.

Pins TFerrisWheel::mSpeed (+0x140) to a runaway value, but ONLY when the
current mission is the runaway scenario (gpMarDirector+0x7D == 2). In any other
level the wheel is left untouched (normal slow spin). Target speed is read from
/tmp/ferris_speed each loop so it can be retuned without restarting.

  gpMarDirector = 0x8040E178 ; deref, byte +0x7D == 2 => Runaway Ferris Wheel
  TFerrisWheel  ; vtable 0x803D10AC ; mSpeed f32 @ +0x140
                ; runaway-intended value at 120fps ~= 10.0 * SMSGetAnmFrameRate(0.5) = 5.0

Usage: python3 ferris_pin.py         # pins in Ep5 to value in /tmp/ferris_speed (default 5.0)
       echo 8 > /tmp/ferris_speed    # retune live
       echo 0 > /tmp/ferris_speed    # 0 = release (stop pinning)
"""
import struct, time
from gcmem import DolphinMem, find_dolphin_pid

VT = b'\x80\x3d\x10\xac'          # __vt__12TFerrisWheel = 0x803D10AC
GUEST = 0x80000000
GP_MARDIRECTOR = 0x8040E178
SPEED_FILE = "/tmp/ferris_speed"

def target():
    try:
        return float(open(SPEED_FILE).read().strip())
    except Exception:
        return 5.0

def find_mem1(mem):
    for rb, rs in mem._regions():
        if rs >= 0x01800000 and mem._raw_read(rb, 4) == b"GMSE":
            mem._mem1_host_base = rb
            return True
    return False

def rd_u32(mem, a):
    b = mem.read(a, 4)
    return struct.unpack('>I', b)[0] if b else 0

def scenario(mem):
    gp = rd_u32(mem, GP_MARDIRECTOR)
    if not (GUEST <= gp < GUEST + 0x1800000):
        return None
    b = mem.read(gp + 0x7D, 1)
    return b[0] if b else None

def find_wheel(mem):
    for off in range(0, 0x1800000, 0x100000):
        data = mem.read(GUEST + off, 0x100000)
        if not data:
            continue
        i = data.find(VT)
        while i != -1:
            if i % 4 == 0:
                return GUEST + off + i
            i = data.find(VT, i + 1)
    return None

def main():
    mem = DolphinMem(find_dolphin_pid())
    if not find_mem1(mem):
        print("MEM1 not found"); return
    inst = None
    last_state = None
    while True:
        sc = scenario(mem)
        armed = (sc == 2)          # runaway mission only
        if armed:
            if inst is None or mem.read(inst, 4) != VT:
                inst = find_wheel(mem)
            spd = target()
            if inst is not None and spd > 0:
                mem.write(inst + 0x140, struct.pack('>f', spd))
        else:
            inst = None
        if armed != last_state:
            print(f"[ferris] scenario={sc} armed={armed}")
            last_state = armed
        time.sleep(0.033)

if __name__ == "__main__":
    main()
