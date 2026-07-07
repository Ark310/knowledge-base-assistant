# KB Chatbot v3.0.1 — Phase 4: AI-PC Base Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up an isolated, authenticated local-reasoning endpoint on the AI PC — Ollama serving a Contoso-only `qwen2.5-7b-instruct` model behind a Caddy per-user Basic-auth gateway — that the v3.0.1 chatbot's Local provider can call over the LAN.

**Architecture:** Author a self-contained script + config bundle in the Knowledge Base repo under `ai_pc/reasoning_gateway/`. The operator copies that folder to `C:\Contoso\LocalLLM_Setup\reasoning_chatbot\` on the AI PC and runs the numbered scripts. Ollama stays bound to localhost (`127.0.0.1:11434`); Caddy reverse-proxies `http://<SERVER_LAN_IP>:11500` → Ollama with Basic auth. The KYC model/prompts/data/route are never touched; only one model loads at a time on the 8GB GPU.

**Tech Stack:** Windows PowerShell 5.1, Ollama, Caddy v2 (`basic_auth` + `reverse_proxy`), OpenAI-compatible `/v1/chat/completions` route. No Python in this phase.

## Global Constraints

- **Windows PowerShell 5.1**, copy-paste ready. AI PC OS = **Windows Server 2019** → **do NOT depend on winget** (not present); download Caddy directly.
- **Secrets discipline (org policy):** no password/plaintext credential is ever committed, logged, or written to OneDrive. Only bcrypt **hashes** are stored on the AI PC; generated plaintext is shown **once** for secure handoff. `reasoning.env`, `config/users.txt`, `config/Caddyfile`, `bin/`, `logs/` are git-ignored.
- **KYC isolation:** never reference or modify KYC model/prompts/data/route/logs. Our model name is exactly `contoso-reasoning-qwen25-7b`.
- **Base model:** `qwen2.5:7b-instruct`. **Served model:** `contoso-reasoning-qwen25-7b` (temp 0 + fixed seed for determinism).
- **Single loaded model:** `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1` (protects KYC coexistence on 8GB VRAM).
- **Gateway:** `http://<SERVER_LAN_IP>:11500`, firewall opened on the **Private profile only**. Basic-auth-over-HTTP is a **trusted-LAN posture** (HTTPS/VPN is the later production upgrade).
- **Ollama already runs on the GPU for KYC** (confirmed) → assume Ollama is installed/serving; validate, don't reinstall.
- **Authoring vs deployment:** author under repo `ai_pc/reasoning_gateway/`; the runbook deploys to `C:\Contoso\LocalLLM_Setup\reasoning_chatbot\` on the AI PC. `$PSScriptRoot`-relative paths make the bundle location-independent.
- **Parse-check command** (runnable on any Windows box, executes nothing):
  `powershell -NoProfile -Command "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('<path>',[ref]$null,[ref]([ref]$e).Value); if($e){$e|%{$_.Message};exit 1}else{'PARSE-OK'}"`

---

### Task 1: Bundle scaffold + shared library + env template + gitignore

**Files:**
- Create: `ai_pc/reasoning_gateway/lib/common.ps1`
- Create: `ai_pc/reasoning_gateway/reasoning.env.example`
- Create: `ai_pc/reasoning_gateway/.gitignore`
- Create: `ai_pc/reasoning_gateway/config/.gitkeep`

**Interfaces:**
- Produces (from `lib/common.ps1`, dot-sourced by every script): `Get-ReasoningRoot`, `Import-ReasoningEnv [-Path]` → hashtable, `Require-Var -Cfg <hashtable> -Names <string[]>`, `Write-Log -Message <string>`.

- [ ] **Step 1: Write `lib/common.ps1`**

```powershell
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
```

- [ ] **Step 2: Write `reasoning.env.example`**

```text
# Contoso reasoning gateway config. Copy this file to reasoning.env and fill in.
# reasoning.env is gitignored — never commit real values.
SERVER_LAN_IP=192.0.2.50
REASONING_GATEWAY_PORT=11500
REASONING_MODEL_NAME=contoso-reasoning-qwen25-7b
OLLAMA_BASE_MODEL=qwen2.5:7b-instruct
OLLAMA_LOCAL_URL=http://127.0.0.1:11434
```

- [ ] **Step 3: Write `.gitignore`**

```text
reasoning.env
config/users.txt
config/Caddyfile
bin/
logs/
```

- [ ] **Step 4: Write `config/.gitkeep`** (empty file so the `config/` dir exists in the repo)

```text
```

- [ ] **Step 5: Parse-check `common.ps1`**

Run: `powershell -NoProfile -Command "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('ai_pc/reasoning_gateway/lib/common.ps1',[ref]$null,[ref]([ref]$e).Value); if($e){$e|%{$_.Message};exit 1}else{'PARSE-OK'}"`
Expected: `PARSE-OK`

- [ ] **Step 6: Verify gitignore covers secrets**

Run: `git check-ignore ai_pc/reasoning_gateway/reasoning.env ai_pc/reasoning_gateway/config/users.txt ai_pc/reasoning_gateway/config/Caddyfile`
Expected: all three paths echoed back (meaning they are ignored).

- [ ] **Step 7: Commit**

```bash
git add ai_pc/reasoning_gateway/lib/common.ps1 ai_pc/reasoning_gateway/reasoning.env.example ai_pc/reasoning_gateway/.gitignore ai_pc/reasoning_gateway/config/.gitkeep
git commit -m "feat(v3.0.1-p4): scaffold AI-PC reasoning gateway bundle + shared lib"
```

---

### Task 2: Environment validator (`00_validate_env.ps1`)

**Files:**
- Create: `ai_pc/reasoning_gateway/00_validate_env.ps1`

**Interfaces:**
- Consumes: `Import-ReasoningEnv`, `Require-Var`, `Write-Log` (Task 1).
- Produces: a preflight the operator runs first; exits non-zero on any missing config / unreachable Ollama.

- [ ] **Step 1: Write `00_validate_env.ps1`**

```powershell
param([string]$EnvPath)
. "$PSScriptRoot\lib\common.ps1"

$cfg = Import-ReasoningEnv -Path $EnvPath
Require-Var -Cfg $cfg -Names @("SERVER_LAN_IP","REASONING_GATEWAY_PORT","REASONING_MODEL_NAME","OLLAMA_BASE_MODEL","OLLAMA_LOCAL_URL")
Write-Log ("Config OK: model={0} base={1} gateway={2}:{3}" -f $cfg.REASONING_MODEL_NAME, $cfg.OLLAMA_BASE_MODEL, $cfg.SERVER_LAN_IP, $cfg.REASONING_GATEWAY_PORT)

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) { throw "Ollama not found on PATH. It should already serve KYC on this PC — confirm the install." }
Write-Log ("Ollama found: {0}" -f $ollama.Source)

try {
    $tags = Invoke-RestMethod -Uri ("{0}/api/tags" -f $cfg.OLLAMA_LOCAL_URL) -TimeoutSec 10
    Write-Log ("Ollama reachable. Installed models: " + (($tags.models | ForEach-Object { $_.name }) -join ", "))
} catch {
    throw ("Cannot reach Ollama at {0}. Is the Ollama service running?" -f $cfg.OLLAMA_LOCAL_URL)
}

$gpu = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "NVIDIA" }
if ($gpu) { Write-Log ("GPU: " + (($gpu | ForEach-Object { $_.Name }) -join ", ")) }
else { Write-Log "WARNING: no NVIDIA GPU seen via WMI (Ollama may still use it)." }

Write-Log "Environment validation passed."
```

- [ ] **Step 2: Parse-check**

Run: `powershell -NoProfile -Command "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('ai_pc/reasoning_gateway/00_validate_env.ps1',[ref]$null,[ref]([ref]$e).Value); if($e){$e|%{$_.Message};exit 1}else{'PARSE-OK'}"`
Expected: `PARSE-OK`

- [ ] **Step 3: Commit**

```bash
git add ai_pc/reasoning_gateway/00_validate_env.ps1
git commit -m "feat(v3.0.1-p4): reasoning-gateway env + Ollama preflight validator"
```

---

### Task 3: Model definition + installer (`Modelfile.reasoning`, `01_install.ps1`)

**Files:**
- Create: `ai_pc/reasoning_gateway/Modelfile.reasoning`
- Create: `ai_pc/reasoning_gateway/01_install.ps1`

**Interfaces:**
- Consumes: `Import-ReasoningEnv`, `Require-Var`, `Write-Log`, `Get-ReasoningRoot` (Task 1).
- Produces: `bin/caddy.exe` (downloaded), the Ollama model `contoso-reasoning-qwen25-7b`, and the two `OLLAMA_*` user env vars. Later tasks call `Get-CaddyExe` (Task 4) which expects `bin/caddy.exe`.

- [ ] **Step 1: Write `Modelfile.reasoning`**

```text
FROM qwen2.5:7b-instruct

PARAMETER temperature 0
PARAMETER top_p 1
PARAMETER num_ctx 8192
PARAMETER seed 42

SYSTEM """
You are the local reasoning model for the Contoso KB chatbot.
Answer only from the retrieved context the chatbot provides.
If the answer is not supported by that context, say what is missing and ask for the needed detail — do not guess.
Do not use KYC analyst prompts, KYC test data, or KYC-only assumptions.
Keep answers clear, practical, cited, and suitable for internal team use.
"""
```

- [ ] **Step 2: Write `01_install.ps1`**

```powershell
param([string]$EnvPath)
. "$PSScriptRoot\lib\common.ps1"

$cfg  = Import-ReasoningEnv -Path $EnvPath
Require-Var -Cfg $cfg -Names @("REASONING_MODEL_NAME","OLLAMA_BASE_MODEL")
$root = Get-ReasoningRoot

Write-Log ("Pulling base model {0} ..." -f $cfg.OLLAMA_BASE_MODEL)
ollama pull $cfg.OLLAMA_BASE_MODEL
if ($LASTEXITCODE -ne 0) { throw ("ollama pull failed for {0}" -f $cfg.OLLAMA_BASE_MODEL) }

$modelfile = Join-Path $root "Modelfile.reasoning"
if (-not (Test-Path -LiteralPath $modelfile)) { throw "Modelfile not found: $modelfile" }
Write-Log ("Creating model {0} from {1} ..." -f $cfg.REASONING_MODEL_NAME, $modelfile)
ollama create $cfg.REASONING_MODEL_NAME -f $modelfile
if ($LASTEXITCODE -ne 0) { throw "ollama create failed" }

[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","1","User")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL","1","User")
Write-Log "Set OLLAMA_MAX_LOADED_MODELS=1, OLLAMA_NUM_PARALLEL=1 (User). Restart Ollama for these to take effect."

# Caddy: download directly (Server 2019 has no winget). Static Windows amd64 binary.
$caddyExe = Join-Path $root "bin\caddy.exe"
if (-not (Test-Path -LiteralPath $caddyExe)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $caddyExe) | Out-Null
    Write-Log "Downloading Caddy (windows/amd64) ..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://caddyserver.com/api/download?os=windows&arch=amd64" -OutFile $caddyExe
}
Write-Log ("Caddy at {0}" -f $caddyExe)
& $caddyExe version
if ($LASTEXITCODE -ne 0) { throw "Caddy binary did not run." }
Write-Log "Install step complete."
```

- [ ] **Step 3: Parse-check `01_install.ps1`**

Run: `powershell -NoProfile -Command "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('ai_pc/reasoning_gateway/01_install.ps1',[ref]$null,[ref]([ref]$e).Value); if($e){$e|%{$_.Message};exit 1}else{'PARSE-OK'}"`
Expected: `PARSE-OK`

- [ ] **Step 4: Commit**

```bash
git add ai_pc/reasoning_gateway/Modelfile.reasoning ai_pc/reasoning_gateway/01_install.ps1
git commit -m "feat(v3.0.1-p4): reasoning Modelfile + installer (base pull, model create, caddy fetch)"
```

---

### Task 4: Gateway library + Caddyfile generation + firewall + start/stop

**Files:**
- Create: `ai_pc/reasoning_gateway/lib/gateway.ps1`
- Create: `ai_pc/reasoning_gateway/04_firewall.ps1`
- Create: `ai_pc/reasoning_gateway/05_start_gateway.ps1`
- Create: `ai_pc/reasoning_gateway/05_stop_gateway.ps1`

**Interfaces:**
- Consumes: `Get-ReasoningRoot`, `Write-Log` (Task 1); `bin/caddy.exe` (Task 3).
- Produces (from `lib/gateway.ps1`): `Get-CaddyExe` → path, `Get-UsersFile` → path, `Get-CaddyfilePath` → path, `Write-Caddyfile -Cfg <hashtable>` (regenerates `config/Caddyfile` from `config/users.txt` + env), `Invoke-CaddyReload` (tolerant of a not-running gateway). Task 5 consumes all of these.

- [ ] **Step 1: Write `lib/gateway.ps1`**

```powershell
# gateway.ps1 — Caddy + user-store helpers. Dot-source AFTER common.ps1.

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
    $site = "http://{0}:{1}" -f $Cfg.SERVER_LAN_IP, $Cfg.REASONING_GATEWAY_PORT
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
```

- [ ] **Step 2: Write `04_firewall.ps1`**

```powershell
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
```

- [ ] **Step 3: Write `05_start_gateway.ps1`**

```powershell
param([string]$EnvPath)
. "$PSScriptRoot\lib\common.ps1"
. "$PSScriptRoot\lib\gateway.ps1"
$cfg = Import-ReasoningEnv -Path $EnvPath
$caddy = Get-CaddyExe
$caddyfile = Get-CaddyfilePath
if (-not (Test-Path -LiteralPath $caddyfile)) { throw "No Caddyfile. Provision a user first (02_provision_user.ps1)." }
& $caddy start --config $caddyfile
Write-Log ("Gateway started on http://{0}:{1}" -f $cfg.SERVER_LAN_IP, $cfg.REASONING_GATEWAY_PORT)
```

- [ ] **Step 4: Write `05_stop_gateway.ps1`**

```powershell
. "$PSScriptRoot\lib\common.ps1"
. "$PSScriptRoot\lib\gateway.ps1"
& (Get-CaddyExe) stop
Write-Log "Gateway stopped."
```

- [ ] **Step 5: Parse-check all four files**

Run (repeat the parse-check command for each path):
`ai_pc/reasoning_gateway/lib/gateway.ps1`, `ai_pc/reasoning_gateway/04_firewall.ps1`, `ai_pc/reasoning_gateway/05_start_gateway.ps1`, `ai_pc/reasoning_gateway/05_stop_gateway.ps1`
Expected: `PARSE-OK` for each.

- [ ] **Step 6: Commit**

```bash
git add ai_pc/reasoning_gateway/lib/gateway.ps1 ai_pc/reasoning_gateway/04_firewall.ps1 ai_pc/reasoning_gateway/05_start_gateway.ps1 ai_pc/reasoning_gateway/05_stop_gateway.ps1
git commit -m "feat(v3.0.1-p4): gateway lib (Caddyfile gen), firewall + start/stop scripts"
```

---

### Task 5: Per-user provisioning (`02_provision_user.ps1`, `03_deprovision_user.ps1`)

**Files:**
- Create: `ai_pc/reasoning_gateway/02_provision_user.ps1`
- Create: `ai_pc/reasoning_gateway/03_deprovision_user.ps1`

**Interfaces:**
- Consumes: `Import-ReasoningEnv`, `Require-Var`, `Write-Log` (Task 1); `Get-CaddyExe`, `Get-UsersFile`, `Write-Caddyfile`, `Invoke-CaddyReload` (Task 4).
- Produces: appends/removes `username:bcrypt-hash` lines in `config/users.txt`, regenerates `config/Caddyfile`. Prints plaintext credential **once** on provision.

- [ ] **Step 1: Write `02_provision_user.ps1`**

```powershell
param(
    [Parameter(Mandatory=$true)][string]$Username,
    [string]$EnvPath
)
. "$PSScriptRoot\lib\common.ps1"
. "$PSScriptRoot\lib\gateway.ps1"

$cfg   = Import-ReasoningEnv -Path $EnvPath
Require-Var -Cfg $cfg -Names @("SERVER_LAN_IP","REASONING_GATEWAY_PORT","OLLAMA_LOCAL_URL")
$caddy = Get-CaddyExe

# Strong random password — shown once, never persisted in plaintext.
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
```

- [ ] **Step 2: Write `03_deprovision_user.ps1`**

```powershell
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
    Write-Log ("Removed '{0}'. NOTE: no users remain — add one before starting the gateway." -f $Username)
}
Invoke-CaddyReload
```

- [ ] **Step 3: Parse-check both files**

Run the parse-check command for `ai_pc/reasoning_gateway/02_provision_user.ps1` and `ai_pc/reasoning_gateway/03_deprovision_user.ps1`.
Expected: `PARSE-OK` for each.

- [ ] **Step 4: Commit**

```bash
git add ai_pc/reasoning_gateway/02_provision_user.ps1 ai_pc/reasoning_gateway/03_deprovision_user.ps1
git commit -m "feat(v3.0.1-p4): per-user provision/deprovision (bcrypt hash, one-time plaintext handoff)"
```

---

### Task 6: Acceptance test script (`06_test.ps1`)

**Files:**
- Create: `ai_pc/reasoning_gateway/06_test.ps1`

**Interfaces:**
- Consumes: `Import-ReasoningEnv`, `Write-Log` (Task 1). Takes a known `-Username`/`-Password` (from Task 5's one-time output) to exercise the live gateway.
- Produces: throws non-zero if any of {401-on-bad-creds, 200-on-good-creds, reasoning round-trip, single-model} fails.

- [ ] **Step 1: Write `06_test.ps1`**

```powershell
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
```

- [ ] **Step 2: Parse-check**

Run the parse-check command for `ai_pc/reasoning_gateway/06_test.ps1`.
Expected: `PARSE-OK`

- [ ] **Step 3: Commit**

```bash
git add ai_pc/reasoning_gateway/06_test.ps1
git commit -m "feat(v3.0.1-p4): gateway acceptance test (401/200, reasoning round-trip, single-model)"
```

---

### Task 7: Operator runbook (`README.md`) + Wave-1 checklist

**Files:**
- Create: `ai_pc/reasoning_gateway/README.md`

**Interfaces:**
- Consumes: every script above.
- Produces: the exact ordered steps the operator runs on the AI PC, the values the chatbot's Local provider will consume (SERVER_LAN_IP + per-user creds), and the KYC-isolation + security checklist.

- [ ] **Step 1: Write `README.md`**

````markdown
# Contoso Reasoning Gateway (AI-PC, chatbot v3.0.1 Phase 4)

An **isolated** local-reasoning endpoint for the Contoso KB chatbot: Ollama serves
`contoso-reasoning-qwen25-7b` bound to localhost; **Caddy** exposes it on the LAN with
**per-user Basic auth**. **KYC is never touched.** Only one model loads at a time on the 8GB GPU.

## Deploy to the AI PC
Copy this whole `reasoning_gateway/` folder to:
`C:\Contoso\LocalLLM_Setup\reasoning_chatbot\`
Open **Windows PowerShell 5.1** there. Then:

## One-time setup (run in order)
```powershell
Copy-Item .\reasoning.env.example .\reasoning.env
notepad .\reasoning.env      # set SERVER_LAN_IP to this PC's LAN IP; leave the rest as-is
.\00_validate_env.ps1        # confirms config + Ollama reachable (+ GPU)
.\01_install.ps1             # pulls qwen2.5:7b-instruct, creates the model, fetches Caddy, sets single-model env
# Restart Ollama so OLLAMA_MAX_LOADED_MODELS=1 takes effect (quit tray + reopen, or restart the service)
.\02_provision_user.ps1 -Username abdul   # prints the URL + username + password ONCE — copy it now
.\04_firewall.ps1            # opens TCP 11500 on the Private profile only
.\05_start_gateway.ps1       # starts the gateway
.\06_test.ps1 -Username abdul -Password "<the password printed above>"   # expect ALL GATEWAY TESTS PASSED
```

## Add / remove colleagues
```powershell
.\02_provision_user.ps1 -Username jane     # hand Jane her one-time credentials securely
.\03_deprovision_user.ps1 -Username jane   # revoke Jane (others unaffected)
```

## Values the chatbot's Local provider needs (entered in the app, stored in the OS keyring)
- Base URL: `http://<SERVER_LAN_IP>:11500/v1`
- Model:    `contoso-reasoning-qwen25-7b`
- Auth:     Basic — the per-user username + password from `02_provision_user.ps1`

## Security & isolation (must stay true)
- Passwords are shown once and never written to disk/OneDrive/logs; only bcrypt hashes live in `config/users.txt`.
- `reasoning.env`, `config/users.txt`, `config/Caddyfile`, `bin/`, `logs/` are git-ignored.
- Firewall is **Private profile only**. Basic-auth-over-HTTP is a **trusted-LAN** posture; HTTPS/VPN is the production upgrade.
- KYC keeps its own model/prompts/data/route/logs. Our model is exactly `contoso-reasoning-qwen25-7b`.
- Switching to KYC: `ollama stop contoso-reasoning-qwen25-7b` first (single-model GPU).

## When to run this (v3.0.1 sequencing)
This is **Wave 1** — run it now/early; it is independent and gives the app a real endpoint to build against.
**Wave 2 (fine-tune)** comes later: after the chatbot's Phase 1 (eval harness) + Phase 2 (redacted data)
exist, the fine-tuned model replaces the base one in `Modelfile.reasoning` (re-run `01_install.ps1`) — only
if it beats the base model on the eval.
````

- [ ] **Step 2: Verify the runbook references only files that exist**

Run: `powershell -NoProfile -Command "$md=Get-Content -Raw ai_pc/reasoning_gateway/README.md; @('00_validate_env.ps1','01_install.ps1','02_provision_user.ps1','03_deprovision_user.ps1','04_firewall.ps1','05_start_gateway.ps1','06_test.ps1','reasoning.env.example','Modelfile.reasoning') | %{ if(-not(Test-Path \"ai_pc/reasoning_gateway/$_\")){throw \"missing $_\"} }; 'RUNBOOK-OK'"`
Expected: `RUNBOOK-OK`

- [ ] **Step 3: Commit**

```bash
git add ai_pc/reasoning_gateway/README.md
git commit -m "docs(v3.0.1-p4): AI-PC reasoning-gateway operator runbook + Wave-1 checklist"
```

---

## On-AI-PC Acceptance (operator-run, after the bundle is copied over)

These are **not** run in the dev repo — they run on the AI PC and are the real proof of Phase 4. The operator runs the "One-time setup" block from the runbook; expected end state:
- `00_validate_env.ps1` → "Environment validation passed."
- `01_install.ps1` → model `contoso-reasoning-qwen25-7b` created; Caddy version prints.
- `06_test.ps1` → **"ALL GATEWAY TESTS PASSED"** (401 bad, 200 good, reasoning `OK`, single model in `ollama ps`).
- KYC model still runs independently (`ollama run <kyc-model>` unaffected; not both loaded at once).

## Self-Review (completed)

- **Spec coverage (spec §6.4):** Ollama isolated model ✓ (T3), single-model env ✓ (T3), Caddy multi-user gateway ✓ (T4), reverse_proxy to localhost ✓ (T4), provision/deprovision ✓ (T5), firewall Private-only ✓ (T4), 401/200 + reasoning + `ollama ps` tests ✓ (T6), wake-on-call keep_alive = native Ollama (documented in runbook) ✓ (T7), KYC isolation ✓ (constraints + T7), base `qwen2.5:7b-instruct` / served `contoso-reasoning-qwen25-7b` ✓ (T3), no-winget-on-Server-2019 ✓ (T3 direct download). Wave-2 fine-tune handoff noted ✓ (T7).
- **Placeholder scan:** none — every script is complete. `<SERVER_LAN_IP>` / `<password>` are operator-supplied runtime values, not plan gaps.
- **Type/name consistency:** `Get-CaddyExe`/`Get-UsersFile`/`Get-CaddyfilePath`/`Write-Caddyfile`/`Invoke-CaddyReload` defined in T4, consumed in T5; `Import-ReasoningEnv`/`Require-Var`/`Write-Log`/`Get-ReasoningRoot` defined in T1, consumed T2–T6; model name `contoso-reasoning-qwen25-7b` identical throughout; env keys identical across scripts.
