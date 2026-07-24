"""Torch campaign/Stage-3 watchdog — OS-side, session-independent.

Every 15 minutes, unconditionally:
  1. keep-awake: SetProcessInformation ES_CONTINUOUS|ES_SYSTEM_REQUIRED —
     prevents the Windows idle-throttle state (8h stall, July 17);
     auto-reverts when this process exits.
  2. re-applies EcoQoS-off to every pyro/python/stockfish process.
  3. MEMORY GUARD (July 18 OOM: OneDrive leaked 52GB commit and the famine
     killed pyro spawns): logs available RAM; < 800MB -> WARNING;
     < 400MB -> controlled restart of the campaign (kill generator
     pythons + pyro, then resume) — fresh processes beat an OOM massacre.
  4. AUTO-RESUME: pyro count 0 -> invoke resume_campaign.cmd (idempotent:
     its guard exits if engines run; the generator exits if target met).
     30-min cooldown between interventions.

Singleton via localhost port bind. Exits after 2h with no pyro AND no
stockfish (campaign and Stage 3 both finished). Logs to watchdog.log.
"""
import ctypes
import datetime
import glob
import json
import socket
import subprocess
import time
from ctypes import wintypes

LOG = r"C:\torch_data\watchdog.log"
RESUME_CMD = r"C:\torch_data\resume_campaign.cmd"
STATS_GLOB = r"C:\torch_data\selfplay_v2.shard*.stats.json"
CAMPAIGN_DONE = 49_999_000  # no auto-resume once the corpus is complete
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
WARN_MB = 800
RESTART_MB = 400
COOLDOWN_S = 1800


class PPTS(ctypes.Structure):
    _fields_ = [("Version", wintypes.DWORD),
                ("ControlMask", wintypes.DWORD),
                ("StateMask", wintypes.DWORD)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def avail_mb(k32):
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    k32.GlobalMemoryStatusEx(ctypes.byref(m))
    return int(m.ullAvailPhys // (1024 * 1024))


def target_pids():
    out = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    pids = {}
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) < 2:
            continue
        name = parts[0].lower()
        if name.startswith(("pyro", "python", "stockfish")):
            try:
                pids.setdefault(name.split(".")[0].rstrip("0123456789-"), []).append(int(parts[1]))
            except ValueError:
                pass
    return pids


def generator_pids():
    """PIDs of python processes running the generator (not this watchdog)."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
        capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        if "generate_selfplay_v2" in line:
            try:
                pids.append(int(line.split("\t")[0]))
            except ValueError:
                pass
    return pids


def qos_off(pid, k32):
    h = k32.OpenProcess(0x0200, False, pid)
    if not h:
        return False
    s = PPTS(1, 0x1, 0)
    r = k32.SetProcessInformation(h, 4, ctypes.byref(s), ctypes.sizeof(s))
    k32.CloseHandle(h)
    return bool(r)


def corpus_total():
    tot = 0
    for p in glob.glob(STATS_GLOB):
        try:
            with open(p) as f:
                tot += json.load(f).get("positions", 0)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return tot


def invoke_resume(reason):
    log(f"INTERVENTION ({reason}): invoking resume_campaign.cmd")
    subprocess.Popen(["cmd", "/c", RESUME_CMD],
                     creationflags=subprocess.CREATE_NO_WINDOW)


def controlled_restart(pids):
    log("INTERVENTION (memory): controlled campaign restart")
    for pid in generator_pids():
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    for k, group in pids.items():
        if k.startswith("pyro"):
            for pid in group:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    time.sleep(5)
    invoke_resume("memory restart")


def main():
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", 47311))
    except OSError:
        return  # another watchdog is running
    lock.listen(1)

    k32 = ctypes.windll.kernel32
    qos_off(k32.GetCurrentProcessId(), k32)
    log("watchdog v2 started (qos + keep-awake + memory guard + auto-resume)")
    idle_cycles = 0
    last_intervention = 0.0
    while True:
        k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        pids = target_pids()
        n_ok = sum(qos_off(p, k32) for group in pids.values() for p in group)
        mem = avail_mb(k32)
        counts = {k: len(v) for k, v in sorted(pids.items())}
        log(f"qos-off {n_ok} procs {counts}; avail RAM {mem}MB")

        can_act = time.time() - last_intervention > COOLDOWN_S
        # engine names vary (pyro.exe / pyro_campaign.exe /
        # stockfish-windows-x86-64-avx2.exe) — prefix-match BOTH counts
        # against the same name set the qos scan uses, never exact keys
        n_pyro = sum(len(v) for k, v in pids.items() if k.startswith("pyro"))
        n_sf = sum(len(v) for k, v in pids.items() if k.startswith("stockfish"))
        if mem < RESTART_MB and n_pyro > 0 and can_act:
            controlled_restart(pids)
            last_intervention = time.time()
        elif mem < WARN_MB:
            log(f"WARNING: available RAM {mem}MB < {WARN_MB}MB")
        elif n_pyro == 0 and n_sf == 0 and can_act and corpus_total() < CAMPAIGN_DONE:
            invoke_resume("no engines running")
            last_intervention = time.time()

        working = n_pyro or n_sf
        idle_cycles = 0 if working else idle_cycles + 1
        log(f"engines: pyro {n_pyro}  sf {n_sf}  idle_cycles {idle_cycles}/8")
        if idle_cycles >= 8:
            log("no engines for 2h — watchdog exiting (keep-awake released)")
            break
        time.sleep(900)


if __name__ == "__main__":
    main()
