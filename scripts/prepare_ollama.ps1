param([string]$Version = '0.40.16')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskTools = Join-Path $taskRoot '.runtime\tools'
$taskTarget = Join-Path $taskTools ('ollama-' + $Version)
$taskArchive = Join-Path $taskTools ('ollama-' + $Version + '-windows-amd64.zip')
$taskChecksums = Join-Path $taskTools ('ollama-' + $Version + '-sha256sum.txt')
New-Item -ItemType Directory -Path $taskTools -Force | Out-Null
$taskBase = 'https://github.com/ollama/ollama/releases/download/v' + $Version
if (-not (Test-Path -LiteralPath (Join-Path $taskTarget 'ollama.exe'))) {
    & curl.exe --fail --location --retry 3 --output $taskChecksums ($taskBase + '/sha256sum.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Checksum manifest download failed.' }
    $taskLine = Get-Content -LiteralPath $taskChecksums | Where-Object { $_ -match '\s\*?(?:\./)?ollama-windows-amd64\.zip$' }
    if (-not $taskLine) { throw 'Official archive checksum not found.' }
    $taskExpected = ($taskLine -split '\s+')[0]
    if (-not (Test-Path -LiteralPath $taskArchive) -or (Get-FileHash -LiteralPath $taskArchive -Algorithm SHA256).Hash -ne $taskExpected) {
        & curl.exe --fail --location --retry 3 --continue-at - --output $taskArchive ($taskBase + '/ollama-windows-amd64.zip')
        if ($LASTEXITCODE -ne 0) { throw 'Ollama download failed; rerun to resume.' }
    }
    $taskActual = (Get-FileHash -LiteralPath $taskArchive -Algorithm SHA256).Hash
    if ($taskActual -ne $taskExpected) { throw 'Ollama archive checksum mismatch.' }
    New-Item -ItemType Directory -Path $taskTarget -Force | Out-Null
    Expand-Archive -LiteralPath $taskArchive -DestinationPath $taskTarget -Force
    @{version=$Version;sha256=$taskActual;source=($taskBase + '/ollama-windows-amd64.zip')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskTarget 'source.json') -Encoding utf8
}
Write-Output ('Portable Ollama ready: ' + (Join-Path $taskTarget 'ollama.exe'))
