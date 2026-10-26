param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path (Split-Path -Parent $taskRoot) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = 'python' }
Push-Location $taskRoot
try { & $taskPython -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port }
finally { Pop-Location }
