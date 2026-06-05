Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $root "frontend"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  $venvPython = "python"
}

$logsDir = Join-Path $root "outputs\logs"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

function Get-ListeningPid([int]$Port) {
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -eq $conn) { return $null }
  return [int]$conn.OwningProcess
}

function Test-UrlReady([string]$Url, [int]$TimeoutSec = 60) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 3 -UseBasicParsing
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
        return $true
      }
    } catch {
      Start-Sleep -Milliseconds 800
    }
  }
  return $false
}

$backendPid = Get-ListeningPid -Port 8000
$frontendPid = Get-ListeningPid -Port 3000

if ($null -eq $backendPid) {
  $backendOut = Join-Path $logsDir "backend.out.log"
  $backendErr = Join-Path $logsDir "backend.err.log"
  $backendProc = Start-Process -FilePath $venvPython -ArgumentList @("-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $root -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru
  $backendPid = $backendProc.Id
  Write-Host "Started backend PID=$backendPid"
} else {
  Write-Host "Backend already listening on 8000 (PID=$backendPid)"
}

if ($null -eq $frontendPid) {
  $frontendOut = Join-Path $logsDir "frontend.out.log"
  $frontendErr = Join-Path $logsDir "frontend.err.log"
  $frontendProc = Start-Process -FilePath "powershell" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "npm run dev") -WorkingDirectory $frontendDir -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -PassThru
  $frontendPid = $frontendProc.Id
  Write-Host "Started frontend PID=$frontendPid"
} else {
  Write-Host "Frontend already listening on 3000 (PID=$frontendPid)"
}

$pidFile = Join-Path $PSScriptRoot ".dev-pids.json"
@{
  backendPid = $backendPid
  frontendPid = $frontendPid
  startedAt = (Get-Date).ToString("s")
} | ConvertTo-Json | Set-Content -Path $pidFile -Encoding UTF8

$backendReady = Test-UrlReady -Url "http://127.0.0.1:8000/docs" -TimeoutSec 90
$frontendReady = Test-UrlReady -Url "http://localhost:3000" -TimeoutSec 120

Write-Host ""
Write-Host "Backend URL : http://127.0.0.1:8000/docs"
Write-Host "Frontend URL: http://localhost:3000"
Write-Host ""
Write-Host "Backend ready : $backendReady"
Write-Host "Frontend ready: $frontendReady"
Write-Host "Logs dir     : $logsDir"

if (-not $backendReady -or -not $frontendReady) {
  Write-Warning "One or more services are not healthy yet. Check log files under outputs/logs."
}
