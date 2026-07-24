@echo off
rem Torch 50M selfplay campaign — resume/resurrect script (Session 2b Stage 2).
rem Idempotent: exits if the campaign is already running. Resume is lossless
rem (workers continue from shard line counts). Invoked at logon by the
rem Startup-folder launcher (torch_campaign_resume.vbs), and manually for
rem restarts. All binaries fully qualified: a bare `find` can resolve to
rem Git's Unix find through the user PATH and silently break the guard.
echo [%date% %time%] resume invoked >> C:\torch_data\resurrect.log
%SystemRoot%\System32\tasklist.exe /FI "IMAGENAME eq pyro_campaign.exe" | %SystemRoot%\System32\findstr.exe /I "pyro" >nul && echo [%date% %time%] campaign already running - exit >> C:\torch_data\resurrect.log && exit /b 0
rem second guard: catches the pre-engine line-counting phase (pyro absent
rem but a generator python already running) — closes the double-launch race
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\torch_data\check_running.ps1 -Pattern generate_selfplay_v2
if not %errorlevel%==0 echo [%date% %time%] generator already starting - exit >> C:\torch_data\resurrect.log && exit /b 0
echo [%date% %time%] relaunching campaign >> C:\torch_data\resurrect.log
start "" /b "C:\Users\shami\OneDrive\Documents\torch\backend\venv\Scripts\python.exe" C:\torch_data\campaign_watchdog.py
set V2_HEADLESS=1
set V2_ENGINE_PATH=C:\torch_data\pyro_campaign.exe
rem 8 workers post-OOM (headroom over throughput, July 18); target excludes
rem the frozen shards 8+9 (5,631,122 lines) so the corpus still ends at ~50M
cd /d C:\Users\shami\OneDrive\Documents\torch\backend
"C:\Users\shami\OneDrive\Documents\torch\backend\venv\Scripts\python.exe" -u -m scripts.generate_selfplay_v2 --target 44368878 --output C:/torch_data/selfplay_v2 --workers 8 --nodes 4000 --seed 20260716 >> C:\torch_data\campaign_gen3.log 2>&1
