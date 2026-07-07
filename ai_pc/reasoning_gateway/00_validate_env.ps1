param([string]$EnvPath)
. "$PSScriptRoot\lib\common.ps1"

$cfg = Import-ReasoningEnv -Path $EnvPath
Require-Var -Cfg $cfg -Names @("SERVER_LAN_IP","REASONING_GATEWAY_PORT","REASONING_MODEL_NAME","OLLAMA_BASE_MODEL","OLLAMA_LOCAL_URL")
Write-Log ("Config OK: model={0} base={1} gateway={2}:{3}" -f $cfg.REASONING_MODEL_NAME, $cfg.OLLAMA_BASE_MODEL, $cfg.SERVER_LAN_IP, $cfg.REASONING_GATEWAY_PORT)

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) { throw "Ollama not found on PATH. It should already serve KYC on this PC - confirm the install." }
Write-Log ("Ollama found: {0}" -f $ollama.Source)

try {
    $tags = Invoke-RestMethod -Uri ("{0}/api/tags" -f $cfg.OLLAMA_LOCAL_URL) -TimeoutSec 10
    Write-Log ("Ollama reachable. Installed models: " + (($tags.models | ForEach-Object { $_.name }) -join ", "))
} catch {
    throw ("Cannot reach Ollama at {0}. Is the Ollama service running?" -f $cfg.OLLAMA_LOCAL_URL)
}

$gpu = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "NVIDIA" }
if ($gpu) { Write-Log ("GPU: " + (($gpu | ForEach-Object { $_.Name }) -join ", ")) }
else { Write-Log "WARNING: no NVIDIA GPU seen via WMI (Ollama may still use it)." }

Write-Log "Environment validation passed."
