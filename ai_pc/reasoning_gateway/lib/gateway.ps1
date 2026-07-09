# gateway.ps1 - Caddy + user-store helpers. Dot-source AFTER common.ps1.

function Get-CaddyExe {
    $exe = Join-Path (Get-ReasoningRoot) "bin\caddy.exe"
    if (-not (Test-Path -LiteralPath $exe)) { throw "caddy.exe not found at $exe. Run 01_install.ps1 first." }
    return $exe
}
function Get-UsersFile     { return (Join-Path (Get-ReasoningRoot) "config\users.txt") }
function Get-CaddyfilePath { return (Join-Path (Get-ReasoningRoot) "config\Caddyfile") }

function Write-Caddyfile {
    param([hashtable]$Cfg)
    $usersFile = Get-UsersFile
    if (-not (Test-Path -LiteralPath $usersFile)) {
        throw "No users provisioned yet. Run 02_provision_user.ps1 <username> first."
    }
    $userLines = @()
    foreach ($line in Get-Content -LiteralPath $usersFile) {
        $t = $line.Trim()
        if ($t -eq "" -or $t.StartsWith("#")) { continue }
        $idx = $t.IndexOf(":")
        if ($idx -lt 1) { continue }
        $userLines += ("        {0} {1}" -f $t.Substring(0,$idx).Trim(), $t.Substring($idx+1).Trim())
    }
    if ($userLines.Count -eq 0) { throw "users.txt has no valid entries." }
    # Bind all interfaces (":port"), not a single IP, so the gateway is reachable
    # regardless of which NIC/IP the client uses (the AI PC has several adapters).
    # SERVER_LAN_IP stays the address the client/app targets; Basic auth is the guard.
    $site = ":{0}" -f $Cfg.REASONING_GATEWAY_PORT
    $joined = [string]::Join([Environment]::NewLine, $userLines)
    $body = @"
$site {
    basic_auth {
$joined
    }

    reverse_proxy $($Cfg.OLLAMA_LOCAL_URL)
}
"@
    Set-Content -LiteralPath (Get-CaddyfilePath) -Value $body -Encoding utf8
}

function Invoke-CaddyReload {
    $caddy = Get-CaddyExe
    try {
        & $caddy reload --config (Get-CaddyfilePath) 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Log "Gateway reloaded." } else { Write-Log "Gateway not running; change applies on next start." }
    } catch { Write-Log "Gateway not running; change applies on next start." }
}
