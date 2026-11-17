param([string]$ModelsDirectory = '', [string]$Version = '0.40.16')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskExecutable = Join-Path $taskRoot ('.runtime\tools\ollama-' + $Version + '\ollama.exe')
$taskConfiguration = Join-Path $taskRoot '.runtime\ollama-local.json'
if (-not (Test-Path -LiteralPath $taskExecutable)) { throw 'Run scripts/prepare_ollama.ps1 first.' }
if (-not $ModelsDirectory -and (Test-Path -LiteralPath $taskConfiguration)) {
    $ModelsDirectory = (Get-Content -LiteralPath $taskConfiguration -Raw | ConvertFrom-Json).models_directory
}
if (-not $ModelsDirectory) { $ModelsDirectory = $env:OLLAMA_MODELS }
if (-not $ModelsDirectory) { $ModelsDirectory = Join-Path $taskRoot '.runtime\ollama-models' }
$ModelsDirectory = [IO.Path]::GetFullPath($ModelsDirectory)
New-Item -ItemType Directory -Path $ModelsDirectory -Force | Out-Null
@{models_directory=$ModelsDirectory;version=$Version} | ConvertTo-Json | Set-Content -LiteralPath $taskConfiguration -Encoding utf8
$env:OLLAMA_MODELS = $ModelsDirectory
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
& $taskExecutable serve
