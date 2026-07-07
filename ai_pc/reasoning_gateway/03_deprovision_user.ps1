param(
    [Parameter(Mandatory=$true)][string]$Username,
    [string]$EnvPath
)
. "$PSScriptRoot\lib\common.ps1"
. "$PSScriptRoot\lib\gateway.ps1"

$cfg = Import-ReasoningEnv -Path $EnvPath
$usersFile = Get-UsersFile
if (-not (Test-Path -LiteralPath $usersFile)) { throw "No users file at $usersFile" }

$kept = Get-Content -LiteralPath $usersFile | Where-Object { -not ($_ -match ("^\s*{0}\s*:" -f [regex]::Escape($Username))) }
Set-Content -LiteralPath $usersFile -Value $kept -Encoding utf8

try {
    Write-Caddyfile -Cfg $cfg
    Write-Log ("Removed '{0}' and regenerated Caddyfile." -f $Username)
} catch {
    Write-Log ("Removed '{0}'. NOTE: no users remain - add one before starting the gateway." -f $Username)
}
Invoke-CaddyReload
