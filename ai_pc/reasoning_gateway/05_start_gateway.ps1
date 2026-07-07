param([string]$EnvPath)
. "$PSScriptRoot\lib\common.ps1"
. "$PSScriptRoot\lib\gateway.ps1"
$cfg = Import-ReasoningEnv -Path $EnvPath
$caddy = Get-CaddyExe
$caddyfile = Get-CaddyfilePath
if (-not (Test-Path -LiteralPath $caddyfile)) { throw "No Caddyfile. Provision a user first (02_provision_user.ps1)." }
& $caddy start --config $caddyfile
Write-Log ("Gateway started on http://{0}:{1}" -f $cfg.SERVER_LAN_IP, $cfg.REASONING_GATEWAY_PORT)
