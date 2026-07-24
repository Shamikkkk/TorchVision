# Torch campaign heartbeat — session-independent hourly health logger.
# Appends "timestamp | total | delta-rate | workers" to campaign_health.log.
# Reads worker stats.json (updated every 30s, equals shard line counts).
# Exits on its own when the campaign hits the 50M target and workers stop.
$log = 'C:\torch_data\campaign_health.log'
$prevTot = $null; $prevTime = $null
while ($true) {
    $tot = 0
    Get-ChildItem C:\torch_data\selfplay_v2.shard*.stats.json -ErrorAction SilentlyContinue | ForEach-Object {
        try { $tot += (Get-Content $_ -Raw | ConvertFrom-Json).positions } catch {}
    }
    $w = (Get-Process | Where-Object { $_.ProcessName -like 'pyro*' } | Measure-Object).Count
    $now = Get-Date
    if ($null -ne $prevTot -and ($now - $prevTime).TotalSeconds -gt 0) {
        $rate = [math]::Round(($tot - $prevTot) / ($now - $prevTime).TotalSeconds, 1)
    } else { $rate = 'first' }
    Add-Content $log ("{0:yyyy-MM-dd HH:mm:ss} | {1} | {2} | {3}" -f $now, $tot, $rate, $w)
    $prevTot = $tot; $prevTime = $now
    if ($tot -ge 50000000 -and $w -eq 0) { break }
    Start-Sleep -Seconds 3600
}
