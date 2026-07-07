. "$PSScriptRoot\lib\common.ps1"
. "$PSScriptRoot\lib\gateway.ps1"
& (Get-CaddyExe) stop
Write-Log "Gateway stopped."
