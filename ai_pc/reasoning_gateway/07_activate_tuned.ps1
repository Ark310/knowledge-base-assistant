# Create/refresh the tuned Ollama model from the exported GGUF, then serve it.
param([string]$GgufDir = "$PSScriptRoot")
$ErrorActionPreference = "Stop"
Write-Host "Creating tuned model contoso-reasoning-qwen25-7b:v1 ..."
ollama create contoso-reasoning-qwen25-7b:v1 -f "$PSScriptRoot\Modelfile.reasoning.tuned"
Write-Host "Done. Point the gateway at contoso-reasoning-qwen25-7b:v1 and restart it."
