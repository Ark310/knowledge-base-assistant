# Roll the served model back to the stock base by recreating it from the base
# Modelfile (FROM qwen2.5:7b-instruct). The :v1 tuned snapshot is retained.
$ErrorActionPreference = "Stop"
Write-Host "Rolling contoso-reasoning-qwen25-7b back to the base (qwen2.5:7b-instruct) ..."
ollama create contoso-reasoning-qwen25-7b -f "$PSScriptRoot\Modelfile.reasoning"
if ($LASTEXITCODE -ne 0) { throw "ollama create (base) failed" }
Write-Host "Done. Restart the gateway. The :v1 tuned snapshot is retained for re-activation."
