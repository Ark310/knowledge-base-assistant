param([string]$EnvPath)
. "$PSScriptRoot\lib\common.ps1"
$cfg = Import-ReasoningEnv -Path $EnvPath
Require-Var -Cfg $cfg -Names @("REASONING_GATEWAY_PORT")

$name = "Contoso Reasoning Gateway"
$port = [int]$cfg.REASONING_GATEWAY_PORT

# Re-create the rule each run so a stale/too-narrow rule gets corrected (idempotent).
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue

# Open the port on whichever profile(s) the machine's NIC(s) actually use. A
# Private-only rule silently fails on a Domain- or Public-classified NIC -> the
# inbound SYN is dropped -> the client sees a connection TIMEOUT (WinError 10060).
# Get-NetConnectionProfile reports "DomainAuthenticated"; the firewall wants "Domain".
$map = @{ "DomainAuthenticated" = "Domain"; "Private" = "Private"; "Public" = "Public" }
$active = @((Get-NetConnectionProfile).NetworkCategory | ForEach-Object { $map["$_"] } |
            Where-Object { $_ } | Sort-Object -Unique)
if (-not $active) { $active = @("Private") }
$profileArg = ($active -join ",")
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $port -Profile $profileArg | Out-Null
Write-Log ("Opened TCP {0} on profile(s): {1}" -f $port, $profileArg)
Write-Log "Active network profiles on this machine:"
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory |
    Format-Table -AutoSize | Out-String | ForEach-Object { Write-Host $_ }
