param(
  [int[]]$Ports = @(3000, 8000)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-ListeningProcesses([int]$Port) {
  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($conn in $connections) {
    try {
      $proc = Get-Process -Id $conn.OwningProcess -ErrorAction Stop
      [pscustomobject]@{
        Port = $Port
        Id = $proc.Id
        ProcessName = $proc.ProcessName
        Path = $proc.Path
      }
    } catch {
      [pscustomobject]@{
        Port = $Port
        Id = [int]$conn.OwningProcess
        ProcessName = "unknown"
        Path = ""
      }
    }
  }
}

$targets = foreach ($port in $Ports) {
  Get-ListeningProcesses -Port $port
}

$targets = @($targets | Sort-Object Id -Unique)

if ($targets.Count -eq 0) {
  Write-Host "No listening processes found on ports: $($Ports -join ', ')"
  exit 0
}

Write-Host "Stopping MyQuant LAN service listeners:"
foreach ($target in $targets) {
  Write-Host ("- port {0}: PID={1}, process={2}, path={3}" -f $target.Port, $target.Id, $target.ProcessName, $target.Path)
}

foreach ($target in $targets) {
  try {
    Stop-Process -Id $target.Id -Force -ErrorAction Stop
    Write-Host ("Stopped PID={0}" -f $target.Id)
  } catch {
    Write-Warning ("Failed to stop PID={0}: {1}" -f $target.Id, $_.Exception.Message)
  }
}

Start-Sleep -Milliseconds 500

foreach ($port in $Ports) {
  $stillListening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($stillListening) {
    Write-Warning "Port $port is still listening. Check whether another process restarted it."
  } else {
    Write-Host "Port $port is clear."
  }
}
