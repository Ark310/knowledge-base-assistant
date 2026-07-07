param(
    [Parameter(Mandatory=$true)][string]$Username,
    [string]$EnvPath
)
. "$PSScriptRoot\lib\common.ps1"
. "$PSScriptRoot\lib\gateway.ps1"

$cfg   = Import-ReasoningEnv -Path $EnvPath
Require-Var -Cfg $cfg -Names @("SERVER_LAN_IP","REASONING_GATEWAY_PORT","OLLAMA_LOCAL_URL")
$caddy = Get-CaddyExe

# Strong random password - shown once, never persisted in plaintext.
Add-Type -AssemblyName System.Web
$pw = [System.Web.Security.Membership]::GeneratePassword(20, 4)

$hash = & $caddy hash-password --plaintext $pw
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($hash)) { throw "caddy hash-password failed" }

$usersFile = Get-UsersFile
New-Item -ItemType Directory -Force -Path (Split-Path $usersFile) | Out-Null
if (-not (Test-Path -LiteralPath $usersFile)) { Set-Content -LiteralPath $usersFile -Value "# username:bcrypt-hash (no plaintext ever)" -Encoding utf8 }

if (Get-Content -LiteralPath $usersFile | Where-Object { $_ -match ("^\s*{0}\s*:" -f [regex]::Escape($Username)) }) {
    throw ("User '{0}' already exists. Deprovision first to rotate." -f $Username)
}

Add-Content -LiteralPath $usersFile -Value ("{0}:{1}" -f $Username, $hash) -Encoding utf8
Write-Caddyfile -Cfg $cfg
Invoke-CaddyReload
Write-Log ("Provisioned user '{0}'." -f $Username)

Write-Host ""
Write-Host "=============================================================="
Write-Host (" Hand these to {0} securely (shown ONCE):" -f $Username)
Write-Host ("   Gateway URL : http://{0}:{1}/v1" -f $cfg.SERVER_LAN_IP, $cfg.REASONING_GATEWAY_PORT)
Write-Host ("   Username    : {0}" -f $Username)
Write-Host ("   Password    : {0}" -f $pw)
Write-Host " Do NOT save this password to disk, chat, email, or OneDrive."
Write-Host "=============================================================="
