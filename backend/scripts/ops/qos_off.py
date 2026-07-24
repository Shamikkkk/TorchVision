"""Force EcoQoS/power-throttling OFF for the given PIDs (Windows 11).

SetProcessInformation(ProcessPowerThrottling, ControlMask=EXECUTION_SPEED,
StateMask=0) = 'never throttle execution speed for this process'.
Usage: python qos_off.py <pid> [<pid> ...]
"""
import ctypes
import sys
from ctypes import wintypes


class PPTS(ctypes.Structure):
    _fields_ = [("Version", wintypes.DWORD),
                ("ControlMask", wintypes.DWORD),
                ("StateMask", wintypes.DWORD)]


PROCESS_SET_INFORMATION = 0x0200
ProcessPowerThrottling = 4
EXECUTION_SPEED = 0x1

k32 = ctypes.windll.kernel32
ok = fail = 0
for pid in [int(a) for a in sys.argv[1:]]:
    h = k32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if not h:
        print(f"{pid}: OpenProcess failed ({ctypes.get_last_error()})")
        fail += 1
        continue
    s = PPTS(1, EXECUTION_SPEED, 0)  # control speed-throttling; state 0 = never throttle
    r = k32.SetProcessInformation(h, ProcessPowerThrottling, ctypes.byref(s), ctypes.sizeof(s))
    print(f"{pid}: {'OK' if r else 'FAILED err=' + str(k32.GetLastError())}")
    ok += r != 0
    fail += r == 0
    k32.CloseHandle(h)
print(f"done: {ok} ok, {fail} failed")
