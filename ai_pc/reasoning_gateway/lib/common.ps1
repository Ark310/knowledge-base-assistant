# common.ps1 — shared helpers for the Contoso reasoning gateway scripts.
# Dot-source from each script:  . "$PSScriptRoot\lib\common.ps1"
# No secrets are read from or written to source control. reasoning.env is gitignored.

$ErrorActionPreference = "Stop"

function Get-ReasoningRoot {
    # …\reasoning_gateway (parent of the lib\ folder this file lives in)
    return (Split-Path -Parent $PSScriptRoot)
}

function Import-ReasoningEnv {
    param([string]$Path)
    if (-not $Path) { $Path = Join-Path (Get-ReasoningRoot) "reasoning.env" }
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Config file not found: $Path. Copy reasoning.env.example to reasoning.env and fill it in."
    }
    $cfg = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $t = $line.Trim()
        if ($t -eq "" -or $t.StartsWith("#")) { continue }
        $idx = $t.IndexOf("=")
        if ($idx -lt 1) { continue }
        $cfg[$t.Substring(0, $idx).Trim()] = $t.Substring($idx + 1).Trim()
    }
    return $cfg
}

function Require-Var {
    param([hashtable]$Cfg, [string[]]$Names)
    $missing = @()
    foreach ($n in $Names) {
        if (-not $Cfg.ContainsKey($n) -or [string]::IsNullOrWhiteSpace($Cfg[$n])) { $missing += $n }
    }
    if ($missing.Count -gt 0) { throw ("Missing required config values: " + ($missing -join ", ")) }
}

function Write-Log {
    param([string]$Message)
    Write-Host ("[{0}] {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $Message)
}
