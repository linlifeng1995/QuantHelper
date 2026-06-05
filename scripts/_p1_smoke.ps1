param([string]$tid)
$base = 'http://127.0.0.1:8000'

Write-Host '--- running snapshot ---'
$running = (Invoke-RestMethod "$base/api/tasks/running").task
$running | Select-Object id,status,progress,message,action | Format-List

Write-Host '--- conflict 409 ---'
try {
  $b = @{action='sync_latest'} | ConvertTo-Json
  Invoke-RestMethod -Method Post "$base/api/tasks" -Body $b -ContentType 'application/json' | Out-Null
  Write-Host 'NO 409 raised (FAIL)'
} catch {
  Write-Host ("status={0} detail={1}" -f $_.Exception.Response.StatusCode.value__, $_.ErrorDetails.Message)
}

if (-not $tid) { $tid = $running.id }
Write-Host "--- cancel $tid ---"
$c = Invoke-RestMethod -Method Post "$base/api/tasks/$tid/cancel"
$c | Select-Object status,message | Format-List

Start-Sleep -Seconds 8
Write-Host '--- final snapshot ---'
$final = Invoke-RestMethod "$base/api/tasks/$tid"
$final | Select-Object status,progress,message,error,warning,finished_at | Format-List
Write-Host ('stats: ' + ($final.result.stats | ConvertTo-Json -Compress))
