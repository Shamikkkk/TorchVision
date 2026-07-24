@echo off
rem Torch Stage 3 — SF18 relabel resume/resurrect script (Session 2b).
rem PREREQUISITE: C:\torch_data\selfplay_v2_dedup.plain must exist (step a).
rem Idempotent: exits if a relabel is already running (stockfish.exe guard).
rem Resume is chunk-checkpointed (--resume + truncate-reconcile in reeval).
rem At Stage 3 go: move torch_stage3_resume.vbs into the Startup folder and
rem REMOVE torch_campaign_resume.vbs from it (campaign is finished by then).
echo [%date% %time%] stage3 resume invoked >> C:\torch_data\resurrect.log
if not exist C:\torch_data\selfplay_v2_dedup.plain echo [%date% %time%] stage3: dedup input missing - exit >> C:\torch_data\resurrect.log && exit /b 1
%SystemRoot%\System32\tasklist.exe /FI "IMAGENAME eq stockfish-windows-x86-64-avx2.exe" | %SystemRoot%\System32\findstr.exe /I "stockfish" >nul && echo [%date% %time%] stage3 already running - exit >> C:\torch_data\resurrect.log && exit /b 0
rem second guard: catches reeval's input line-counting phase (no stockfish yet)
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\torch_data\check_running.ps1 -Pattern reeval_with_sf18
if not %errorlevel%==0 echo [%date% %time%] stage3 already starting - exit >> C:\torch_data\resurrect.log && exit /b 0
echo [%date% %time%] stage3 relaunching relabel >> C:\torch_data\resurrect.log
start "" /b "C:\Users\shami\OneDrive\Documents\torch\backend\venv\Scripts\python.exe" C:\torch_data\campaign_watchdog.py
set V2_HEADLESS=1
cd /d C:\Users\shami\OneDrive\Documents\torch\backend
"C:\Users\shami\OneDrive\Documents\torch\backend\venv\Scripts\python.exe" -u -m scripts.reeval_with_sf18 --input C:/torch_data/selfplay_v2_dedup.plain --output C:/torch_data/selfplay_v2_sf18.plain --depth 12 --movetime 1000 --workers 10 --chunk 100000 --resume --progress C:/torch_data/reeval_progress_v2.json >> C:\torch_data\stage3_relabel.log 2>&1
