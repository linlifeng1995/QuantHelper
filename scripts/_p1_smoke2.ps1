$base = 'http://127.0.0.1:8000'
Write-Host '--- start fresh task ---'
$b = @{action='sync_latest'; download_workers=2} | ConvertTo-Json
$t1 = Invoke-RestMethod -Method Post "$base/api/tasks" -Body $b -ContentType 'application/json'
Write-Host ("task1 id={0} status={1}" -f $t1.id, $t1.status)

Start-Sleep -Milliseconds 200
Write-Host '--- running snapshot ---'
$r = (Invoke-RestMethod "$base/api/tasks/running").task
$r | Select-Object id,status,progress | Format-List

Write-Host '--- attempt 2nd start (expect 409) ---'
try {
  Invoke-RestMethod -Method Post "$base/api/tasks" -Body $b -ContentType 'application/json' | Out-Null
  Write-Host 'NO 409 raised (FAIL)'
} catch {
  Write-Host ("status={0} detail={1}" -f $_.Exception.Response.StatusCode.value__, $_.ErrorDetails.Message)
}

Write-Host '--- cancel ---'
$c = Invoke-RestMethod -Method Post "$base/api/tasks/$($t1.id)/cancel"
Write-Host ("cancel status={0} msg={1}" -f $c.status, $c.message)

Start-Sleep -Seconds 6
$final = Invoke-RestMethod "$base/api/tasks/$($t1.id)"
Write-Host ("final status={0} progress={1:N4} cancelled={2} pool_refresh_skipped={3}" -f $final.status, $final.progress, $final.result.stats.cancelled, $final.result.stats.pool_refresh_skipped)

Write-Host '--- running after cancel should be null ---'
$r2 = (Invoke-RestMethod "$base/api/tasks/running").task
if ($r2) { Write-Host ("still: id={0} status={1}" -f $r2.id, $r2.status) } else { Write-Host 'null OK' }
