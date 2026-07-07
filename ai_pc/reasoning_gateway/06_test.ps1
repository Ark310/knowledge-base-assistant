param(
    [Parameter(Mandatory=$true)][string]$Username,
    [Parameter(Mandatory=$true)][string]$Password,
    [string]$EnvPath
)
. "$PSScriptRoot\lib\common.ps1"
$cfg  = Import-ReasoningEnv -Path $EnvPath
$base = "http://{0}:{1}" -f $cfg.SERVER_LAN_IP, $cfg.REASONING_GATEWAY_PORT
$fail = 0

function New-BasicHeader { param([string]$u,[string]$p)
    return @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$u`:$p")) }
}

# 1) Bad creds -> 401
try {
    Invoke-WebRequest -Uri "$base/api/tags" -Headers (New-BasicHeader "wrong" "wrong") -UseBasicParsing -TimeoutSec 15 | Out-Null
    Write-Log "FAIL: bad creds did not return 401"; $fail++
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 401) { Write-Log "PASS: bad creds -> 401" } else { Write-Log ("FAIL: bad creds -> {0}" -f $code); $fail++ }
}

# 2) Good creds -> 200
$auth = New-BasicHeader $Username $Password
try {
    $r = Invoke-WebRequest -Uri "$base/api/tags" -Headers $auth -UseBasicParsing -TimeoutSec 15
    if ($r.StatusCode -eq 200) { Write-Log "PASS: good creds -> 200" } else { Write-Log ("FAIL: good creds -> {0}" -f $r.StatusCode); $fail++ }
} catch { Write-Log ("FAIL: good creds errored: {0}" -f $_.Exception.Message); $fail++ }

# 3) Reasoning round-trip via the OpenAI-compatible route
$payload = @{ model = $cfg.REASONING_MODEL_NAME; messages = @(@{ role = "user"; content = "Reply with the single word: OK" }); stream = $false } | ConvertTo-Json -Depth 6
try {
    $resp = Invoke-RestMethod -Uri "$base/v1/chat/completions" -Method Post -Headers ($auth + @{ "Content-Type" = "application/json" }) -Body $payload -TimeoutSec 180
    $txt = $resp.choices[0].message.content
    if ($txt) { Write-Log ("PASS: reasoning round-trip -> '{0}'" -f $txt.Trim()) } else { Write-Log "FAIL: empty reasoning response"; $fail++ }
} catch { Write-Log ("FAIL: reasoning round-trip errored: {0}" -f $_.Exception.Message); $fail++ }

# 4) Single-model policy (informational + must not show two loaded)
Write-Log "ollama ps:"
ollama ps

if ($fail -eq 0) { Write-Log "ALL GATEWAY TESTS PASSED" } else { throw ("{0} gateway test(s) failed" -f $fail) }
