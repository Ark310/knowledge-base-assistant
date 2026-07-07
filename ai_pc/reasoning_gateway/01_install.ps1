param([string]$EnvPath)
. "$PSScriptRoot\lib\common.ps1"

$cfg  = Import-ReasoningEnv -Path $EnvPath
Require-Var -Cfg $cfg -Names @("REASONING_MODEL_NAME","OLLAMA_BASE_MODEL")
$root = Get-ReasoningRoot

Write-Log ("Pulling base model {0} ..." -f $cfg.OLLAMA_BASE_MODEL)
ollama pull $cfg.OLLAMA_BASE_MODEL
if ($LASTEXITCODE -ne 0) { throw ("ollama pull failed for {0}" -f $cfg.OLLAMA_BASE_MODEL) }

$modelfile = Join-Path $root "Modelfile.reasoning"
if (-not (Test-Path -LiteralPath $modelfile)) { throw "Modelfile not found: $modelfile" }
Write-Log ("Creating model {0} from {1} ..." -f $cfg.REASONING_MODEL_NAME, $modelfile)
ollama create $cfg.REASONING_MODEL_NAME -f $modelfile
if ($LASTEXITCODE -ne 0) { throw "ollama create failed" }

[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","1","User")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL","1","User")
Write-Log "Set OLLAMA_MAX_LOADED_MODELS=1, OLLAMA_NUM_PARALLEL=1 (User). Restart Ollama for these to take effect."

# Caddy: download directly (Server 2019 has no winget). Static Windows amd64 binary.
$caddyExe = Join-Path $root "bin\caddy.exe"
if (-not (Test-Path -LiteralPath $caddyExe)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $caddyExe) | Out-Null
    Write-Log "Downloading Caddy (windows/amd64) ..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://caddyserver.com/api/download?os=windows&arch=amd64" -OutFile $caddyExe
}
Write-Log ("Caddy at {0}" -f $caddyExe)
& $caddyExe version
if ($LASTEXITCODE -ne 0) { throw "Caddy binary did not run." }
Write-Log "Install step complete."
