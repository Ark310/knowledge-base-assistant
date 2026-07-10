# Roll the served model back to the stock base tag (instant fallback).
$ErrorActionPreference = "Stop"
Write-Host "Rolling back to base qwen2.5:7b-instruct ..."
ollama pull qwen2.5:7b-instruct
Write-Host "Base model present. Point the gateway back at qwen2.5:7b-instruct and restart it."
