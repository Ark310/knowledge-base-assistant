# Create the tuned Ollama model from the exported GGUF, publish it as the served
# model the chatbot requests (config.LOCAL_MODEL = contoso-reasoning-qwen25-7b),
# and keep a durable :v1 snapshot for rollback. Restart the gateway afterwards.
param([string]$Gguf = "$env:LOCALAPPDATA\ContosoKBChatbot\finetune\contoso-reasoning-qwen25-7b-Q4_K_M.gguf")
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Gguf)) { throw "GGUF not found: $Gguf (run merge_and_export first)" }
$tpl = Get-Content -Raw "$PSScriptRoot\Modelfile.reasoning.tuned"
$resolved = $tpl -replace '(?m)^FROM .*$', ("FROM " + $Gguf)
$tmp = Join-Path $env:TEMP "Modelfile.reasoning.tuned.resolved"
Set-Content -Encoding ascii -LiteralPath $tmp -Value $resolved
Write-Host "Creating contoso-reasoning-qwen25-7b:v1 (snapshot) ..."
ollama create contoso-reasoning-qwen25-7b:v1 -f $tmp
if ($LASTEXITCODE -ne 0) { throw "ollama create :v1 failed" }
Write-Host "Publishing as served model contoso-reasoning-qwen25-7b (what the chatbot requests) ..."
ollama cp contoso-reasoning-qwen25-7b:v1 contoso-reasoning-qwen25-7b
Write-Host "Done. Restart the gateway (05_start_gateway.ps1). Roll back with 08_rollback.ps1."
