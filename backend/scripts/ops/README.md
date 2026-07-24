# Ops armor for long unattended jobs (Session 2b, July 2026)

Durable copies of the campaign/relabel operational scripts. **Deployed copies
live in `C:/torch_data/` (outside OneDrive)** — that is where the resume
scripts, logs, and heartbeats expect each other; this directory is the backup
and the reference for the next campaign.

| Script | Role |
|---|---|
| `campaign_watchdog.py` | 15-min loop: EcoQoS-off for every pyro*/python/stockfish* process, `ES_SYSTEM_REQUIRED` keep-awake, memory guard (<800MB warn, <400MB controlled restart), auto-resume when engines vanish. Singleton via port 47311. Self-exits 2h after all engines finish. |
| `campaign_heartbeat.ps1` / `stage3_heartbeat.ps1` | Hourly `timestamp \| total \| delta-rate \| workers` to `campaign_health.log` (generation / relabel flavors). |
| `resume_campaign.cmd` / `stage3_resume.cmd` | Idempotent resume scripts (command-line-keyed guards, System32-qualified binaries, V2_HEADLESS SIGINT immunity, watchdog spawn). Point a Startup-folder `.vbs` at one for logon resurrection: `CreateObject("WScript.Shell").Run """C:\torch_data\<script>.cmd""", 0, False` |
| `disk_monitor.py` | 5-min free-space poll; below 5GB cleanly kills the relabel tree so the chunk checkpoint can resume instead of corrupting. |
| `qos_off.py` | Manual EcoQoS release for a PID list (the 28→188 pos/s fix). |

Hard-won rules these encode (full stories in HISTORY.md, Session 2b):
SIGINT immunity for headless runs; EcoQoS-off + keep-awake or Windows idle
throttling will stall the box; guards keyed on command line, never process
name; OneDrive quit during campaigns (52GB leak OOM); everything resumable
and detached; verify process state before trusting any "killed" notification.
