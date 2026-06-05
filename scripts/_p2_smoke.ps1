$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:8000'
$body = @{ action = 'sync_latest' } | ConvertTo-Json
$t = Invoke-RestMethod -Method Post -ContentType 'application/json' -Body $body "$base/api/tasks"
Write-Host ("started id={0}" -f $t.id)
Start-Sleep -Seconds 10
$s = Invoke-RestMethod "$base/api/tasks/$($t.id)"
Write-Host ("status={0} progress={1:N4}" -f $s.status, $s.progress)
Write-Host ("message: " + $s.message)
Invoke-RestMethod -Method Post "$base/api/tasks/$($t.id)/cancel" | Out-Null
Start-Sleep -Seconds 10
$f = Invoke-RestMethod "$base/api/tasks/$($t.id)"
Write-Host ("final status={0} cancelled={1} pool_refresh_skipped={2}" -f $f.status, $f.result.stats.cancelled, $f.result.stats.pool_refresh_skipped)
Write-Host ("final message: " + $f.message)
