# Torch Stage 3 heartbeat — hourly relabel progress to campaign_health.log.
# Reads reeval_progress_v2.json (total_written); format matches the campaign
# heartbeat: "timestamp | S3 written | delta-rate | sf18-workers".
# Exits after two consecutive checks with zero stockfish processes.
$log = 'C:\torch_data\campaign_health.log'
$prog = 'C:\torch_data\reeval_progress_v2.json'
$prevTot = $null; $prevTime = $null; $idleChecks = 0
while ($true) {
    $tot = 0
    if (Test-Path $prog) {
        try { $tot = (Get-Content $prog -Raw | ConvertFrom-Json).total_written } catch {}
    }
    $w = (Get-Process | Where-Object { $_.ProcessName -like 'stockfish*' } | Measure-Object).Count
    $now = Get-Date
    if ($null -ne $prevTot -and ($now - $prevTime).TotalSeconds -gt 0) {
        $rate = [math]::Round(($tot - $prevTot) / ($now - $prevTime).TotalSeconds, 1)
    } else { $rate = 'first' }
    Add-Content $log ("{0:yyyy-MM-dd HH:mm:ss} | S3 {1} | {2} | {3}" -f $now, $tot, $rate, $w)
    $prevTot = $tot; $prevTime = $now
    if ($w -eq 0) { $idleChecks++ } else { $idleChecks = 0 }
    if ($idleChecks -ge 2) { break }
    Start-Sleep -Seconds 3600
}
