# Contoso Reasoning Gateway (AI-PC, chatbot v3.0.1 Phase 4)

An **isolated** local-reasoning endpoint for the Contoso KB chatbot: Ollama serves
`contoso-reasoning-qwen25-7b` bound to localhost; **Caddy** exposes it on the LAN with
**per-user Basic auth**. **KYC is never touched.** Only one model loads at a time on the 8GB GPU.

## Deploy to the AI PC
Copy this whole `reasoning_gateway/` folder to:
`C:\Contoso\LocalLLM_Setup\reasoning_chatbot\`
Open **Windows PowerShell 5.1** there. Then run the steps below in order.

## One-time setup (run in order)
```powershell
Copy-Item .\reasoning.env.example .\reasoning.env
notepad .\reasoning.env      # set SERVER_LAN_IP to this PC's LAN IP; leave the rest as-is
.\00_validate_env.ps1        # confirms config + Ollama reachable (+ GPU)
.\01_install.ps1             # pulls qwen2.5:7b-instruct, creates the model, fetches Caddy, sets single-model env
# Restart Ollama so OLLAMA_MAX_LOADED_MODELS=1 takes effect (quit tray + reopen, or restart the service)
.\02_provision_user.ps1 -Username abdul   # prints URL + username + password ONCE - copy it now
.\04_firewall.ps1            # opens TCP 11500 on the NIC's active profile(s) (Domain/Private/Public)
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
- Auth:     Basic - the per-user username + password from `02_provision_user.ps1`

## Security & isolation (must stay true)
- Passwords are shown once and never written to disk/OneDrive/logs; only bcrypt hashes live in `config/users.txt`.
- `reasoning.env`, `config/users.txt`, `config/Caddyfile`, `bin/`, `logs/` are git-ignored.
- Firewall opens 11500 on the NIC's **active profile(s)** (a Domain-joined server uses the Domain profile, not Private). Basic-auth-over-HTTP is a **trusted-LAN** posture; HTTPS/VPN is the production upgrade.
- KYC keeps its own model/prompts/data/route/logs. Our model is exactly `contoso-reasoning-qwen25-7b`.
- Switching to KYC: `ollama stop contoso-reasoning-qwen25-7b` first (single-model GPU).

## When to run this (v3.0.1 sequencing)
This is **Wave 1** - run it now/early; it is independent and gives the app a real endpoint to build against.
**Wave 2 (fine-tune)** comes later: after the chatbot's Phase 1 (eval harness) + Phase 2 (redacted data)
exist, the fine-tuned model replaces the base one in `Modelfile.reasoning` (re-run `01_install.ps1`) - only
if it beats the base model on the eval.
