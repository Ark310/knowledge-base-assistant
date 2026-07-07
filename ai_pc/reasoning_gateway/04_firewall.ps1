param([string]$EnvPath)
. "$PSScriptRoot\lib\common.ps1"
$cfg = Import-ReasoningEnv -Path $EnvPath
Require-Var -Cfg $cfg -Names @("REASONING_GATEWAY_PORT")

$name = "Contoso Reasoning Gateway"
$port = [int]$cfg.REASONING_GATEWAY_PORT
if (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) {
    Write-Log ("Firewall rule already exists: {0}" -f $name); return
}
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private | Out-Null
Write-Log ("Opened TCP {0} on the Private profile only." -f $port)
