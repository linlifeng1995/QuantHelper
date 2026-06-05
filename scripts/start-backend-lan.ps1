Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "outputs\logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$python = Join-Path $root ".venv\Scripts\python.exe"
$logFile = Join-Path $logDir "backend-lan.log"

Set-Location $root
"[$(Get-Date -Format s)] starting backend on 0.0.0.0:8000" | Out-File -FilePath $logFile -Encoding utf8
& $python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 *>> $logFile
