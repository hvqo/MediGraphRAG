param([string]$ModelsDirectory = '', [int]$Port = 8081, [int]$GpuLayers = 26)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskRuntime = Join-Path $taskRoot '.runtime\tools\llama-b12359'
$taskServer = Get-ChildItem -LiteralPath $taskRuntime -Filter 'llama-server.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $taskServer) { throw 'Run python scripts/prepare_llama.py first.' }
if (-not $ModelsDirectory) {
    $taskOllamaConfig = Join-Path $taskRoot '.runtime\ollama-local.json'
    if (Test-Path -LiteralPath $taskOllamaConfig) { $ModelsDirectory = (Get-Content -LiteralPath $taskOllamaConfig -Raw | ConvertFrom-Json).models_directory }
}
if (-not $ModelsDirectory) { throw 'Pass -ModelsDirectory with the directory used by prepare_vision_model.py.' }
$taskPin = Get-Content -LiteralPath (Join-Path $taskRoot 'config\vision-model.json') -Raw | ConvertFrom-Json
$taskModelLayer = $taskPin.manifest.layers | Where-Object mediaType -eq 'application/vnd.ollama.image.model'
$taskProjectorLayer = $taskPin.manifest.layers | Where-Object mediaType -eq 'application/vnd.ollama.image.projector'
$taskModel = Join-Path $ModelsDirectory ('blobs\' + $taskModelLayer.digest.Replace(':','-'))
$taskProjector = Join-Path $ModelsDirectory ('blobs\' + $taskProjectorLayer.digest.Replace(':','-'))
if (-not (Test-Path -LiteralPath $taskModel) -or -not (Test-Path -LiteralPath $taskProjector)) { throw 'Run python scripts/prepare_vision_model.py --directory <models-directory> first.' }
@{runtime='llama.cpp';base_url=('http://127.0.0.1:' + $Port + '/v1');model='qwen3-vl:8b-instruct'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRoot '.runtime\local-inference.json') -Encoding utf8
# Conservative partial GPU offload for a 6GB laptop; the same process serves text and images.
& $taskServer.FullName --model $taskModel --mmproj $taskProjector --alias 'qwen3-vl:8b-instruct' --host 127.0.0.1 --port $Port --ctx-size 8192 --parallel 1 --n-gpu-layers $GpuLayers --no-mmproj-offload --batch-size 128 --ubatch-size 128 --jinja
