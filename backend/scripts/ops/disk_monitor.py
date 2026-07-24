"""Standalone disk monitor for the Stage 3 relabel (July 2026).

Polls C: free space every 5 minutes -> C:/torch_data/disk_monitor.log.
If free < 5GB: cleanly terminates the relabel (master python running
reeval_with_sf18 + stockfish workers) so the chunk-checkpointed job can be
RESUMED rather than corrupted, then keeps monitoring. Never touches
anything else. Exits after 2h with no relabel processes present.
"""
import ctypes
import datetime
import shutil
import subprocess
import time

LOG = r"C:\torch_data\disk_monitor.log"
LIMIT_GB = 5.0


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def relabel_pids():
    """(master_pids, stockfish_pids) via command-line match, not names."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' "
         "-and $_.CommandLine -match 'reeval_with_sf18') -or $_.Name -like "
         "'stockfish*' } | ForEach-Object { \"$($_.ProcessId) $($_.Name)\" }"],
        capture_output=True, text=True).stdout
    masters, sf = [], []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        (sf if parts[1].lower().startswith("stockfish") else masters).append(parts[0])
    return masters, sf


def main():
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # BelowNormal
    log("disk monitor started")
    idle = 0
    while True:
        free_gb = shutil.disk_usage("C:\\").free / 2**30
        masters, sf = relabel_pids()
        log(f"free {free_gb:.1f}GB  relabel masters {len(masters)}  sf {len(sf)}")
        if free_gb < LIMIT_GB and (masters or sf):
            log(f"FREE < {LIMIT_GB}GB — terminating relabel cleanly for later resume")
            for pid in masters:
                subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                               capture_output=True)
            for pid in sf:
                subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
            log("relabel terminated (resume via stage3_resume.cmd when space is freed)")
        idle = idle + 1 if not (masters or sf) else 0
        if idle >= 24:  # 2h without relabel processes
            log("no relabel processes for 2h — monitor exiting")
            break
        time.sleep(300)


if __name__ == "__main__":
    main()
