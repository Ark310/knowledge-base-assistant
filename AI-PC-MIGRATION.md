# AI PC Migration & Chat Continuity Runbook

**Purpose:** stand up this project on the AI PC so ALL work (KB Chatbot, Scraper, and the on-prem fine-tuning) continues there, and resume this Claude Code conversation with full context.

**Read this first on the AI PC.** A fresh `claude` session started in the repo will auto-load `CLAUDE.md` + `.claude/rules/` (they travel in the folder); this doc + the pointers in §7 restore the rest.

---

## 0. Where we are right now (2026-07-13)

- **Branch:** `feat/kb-chatbot-v3.0.1` (latest commit `5562e31`). Do NOT start work on `master`.
- **KB Chatbot v3.0.1 "KB Guru":** COMPLETE + packaged (`dist/ContosoKBChatbot-v3.0.1/`), operator-verified. Hybrid retrieval, 3 providers (Claude/ChatGPT/Local), QtWebEngine web UI, chat history, Settings/onboarding/Learn, all bug fixes. 456 tests. Unmerged (operator's call).
- **Scraper v4.0.4:** COMPLETE + MERGED to master earlier.
- **Phase 5 — on-prem fine-tuning (IN PROGRESS, the active work):**
  - Dataset BUILT on the AI PC: `%LOCALAPPDATA%\ContosoKBChatbot\finetune\train.jsonl` (3858 train / 150 eval).
  - Training **validated working** on the AI PC (RTX 5060 Ti): a 3B QLoRA step ran on the GPU (~74s/step at the old settings). Switched base 7B→**Qwen2.5-3B-Instruct** (7B thrashed 8 GB).
  - **NEXT ACTION:** run the fast validation train, then merge→GGUF→serve→eval. See §8.

Full blow-by-blow is in `.superpowers/sdd/progress.md` (the SDD ledger) — read it.

---

## 1. Three layers (only one is in the folder)

| Layer | Lives where | Travels in the folder copy? |
|---|---|---|
| **Work** — code, `.git` history, `.wolf/`, `.superpowers/sdd/`, `docs/`, `.claude/rules/`, `CLAUDE.md` | in the repo | ✅ yes |
| **Chat + skills** — conversation transcript, auto-memory, plugins/skills, user `settings.json` | `%USERPROFILE%\.claude\` | ❌ no — see §3, §4, §5 |
| **Runtimes** — Python venvs, Chroma index, HF model cache | `scraper\venv`, `%LOCALAPPDATA%`, `~\.cache` | ❌ rebuild — see §6 |

---

## 2. Put the repo at `C:\Knowledge Base`

That's where it already is on the AI PC (user `Administrator`). The Claude Code project is keyed to this path, encoded as **`C--Knowledge-Base`** (used in §4/§5 for transcript + memory placement). If you place it elsewhere, adjust that encoded name (non-alphanumeric chars → `-`).

---

## 3. Skills / plugins (Claude Code is already installed + logged in)

Fastest = replicate the dev machine's Claude Code config. From the DEV machine copy these two items into the AI PC's `%USERPROFILE%\.claude\` (i.e. `C:\Users\Administrator\.claude\`):

- `settings.json`  (has `enabledPlugins` + `mcpServers`)
- the `plugins\` folder  (the plugin/skill cache)

Then in a `claude` session run `/reload-plugins` and verify with `/mcp`.

**Plugins/skills we used (verify all present):** `superpowers`, `frontend-design`, `pr-review-toolkit`, `feature-dev` — all `@claude-plugins-official`; MCP servers `playwright` and `github`. (`artifact-design` and the `claude-code-guide`/`statusline-setup` agents are bundled.)

If you'd rather install clean instead of copying the cache:
```
/plugin install superpowers@claude-plugins-official
/plugin install frontend-design@claude-plugins-official
/plugin install pr-review-toolkit@claude-plugins-official
/plugin install feature-dev@claude-plugins-official
/plugin install playwright@claude-plugins-official
/plugin install github@claude-plugins-official
/reload-plugins
```
Note: the **github** MCP needs its auth/token re-provided on the AI PC.

---

## 4. Resume THIS chat ("do both")

**A. Handoff (reliable):** start `claude` in `C:\Knowledge Base`. It loads `CLAUDE.md` + rules automatically; then read this doc (§0, §8) + `.superpowers/sdd/progress.md`. That fully restores project state even if B fails.

**B. Transcript copy (best-effort scrollback):** copy this session's transcript into the AI-PC project folder:
- FROM (dev): `C:\Users\AbdulRaqeebKhatri\.claude\projects\C--Users-AbdulRaqeebKhatri-OneDrive---Contoso-Global-Technologies-Inc-Documents-Knowledge-Base\c225a7b5-a64c-42e8-874c-07e749080786.jsonl`
- TO (AI PC): `C:\Users\Administrator\.claude\projects\C--Knowledge-Base\c225a7b5-a64c-42e8-874c-07e749080786.jsonl` (create the folder if needed)

Then:
```
cd "C:\Knowledge Base"
claude --resume c225a7b5-a64c-42e8-874c-07e749080786
```
(or just `claude --resume` and pick it from the list). Old tool-output paths in the scrollback point at the dev machine — cosmetic; new work runs on the AI PC. If the picker can't find it, fall back to A.

---

## 5. Auto-memory

Copy the memory folder so recalled facts carry over:
- FROM (dev): `C:\Users\AbdulRaqeebKhatri\.claude\projects\C--Users-AbdulRaqeebKhatri-OneDrive---Contoso-Global-Technologies-Inc-Documents-Knowledge-Base\memory\`
- TO (AI PC): `C:\Users\Administrator\.claude\projects\C--Knowledge-Base\memory\`

---

## 6. Rebuild runtimes (everything runs on the AI PC)

**The copied `scraper\venv` will NOT work** (absolute paths baked in) — delete it and rebuild:
```
cd "C:\Knowledge Base"
rmdir /s /q scraper\venv
py -m venv scraper\venv
scraper\venv\Scripts\python.exe -m pip install --upgrade pip
scraper\venv\Scripts\python.exe -m pip install -r scraper\requirements.txt
scraper\venv\Scripts\python.exe -m pip install -r Dev\kb_chatbot\requirements.txt
scraper\venv\Scripts\python.exe -m playwright install chromium
```
This is the shared env for BOTH the chatbot and the scraper (and the test suite).

**Training venv `C:\train-venv`** — already set up on the AI PC (cu128 PyTorch for Blackwell + peft + bitsandbytes + datasets + transformers + accelerate + gguf + chromadb + sentence-transformers + rank-bm25 + keyring). Keep it.

**Chroma index** — already copied to `%LOCALAPPDATA%\ContosoKBChatbot\chroma` on the AI PC. Verify: `dir "%LOCALAPPDATA%\ContosoKBChatbot\chroma"` (chroma.sqlite3 + a UUID segment folder).

**HF model cache** — the embed/reranker models + Qwen2.5-3B are already downloaded on the AI PC (from the build + train runs). No action.

---

## 7. Verify the AI-PC environment

```
claude --version            # Claude Code present
git -C "C:\Knowledge Base" log --oneline -1     # expect 5562e31 or later
scraper\venv\Scripts\python.exe -m pytest Dev\kb_chatbot\tests -q   # chatbot suite (train_qlora tests skip here; that's fine)
```
In a `claude` session: `/mcp` (playwright + github connected), `/context`, `/memory`.

**Pointers to restore full context:**
- `.superpowers/sdd/progress.md` — the execution ledger (every task + fix, all phases).
- `.wolf/cerebrum.md` — cross-session learnings + Do-Not-Repeat.
- `.wolf/buglog.json` — logged bugs/fixes (through bug-171).
- `docs/superpowers/specs/2026-07-10-kb-chatbot-v3.0.1-phase5-finetune-design.md` — the fine-tuning spec.
- `docs/superpowers/plans/2026-07-10-kb-chatbot-v3.0.1-phase5-finetune.md` — the P5 plan.
- `Dev/kb_chatbot/finetune/README.md` — the operator training runbook.

---

## 8. Resume the actual work (Phase 5 fine-tuning)

1. **Fast validation train** (~15–20 min, proves end-to-end):
   ```
   cd "C:\Knowledge Base"
   C:\train-venv\Scripts\python.exe -m Dev.kb_chatbot.finetune.train_qlora --epochs 1 --seq-len 1024 --max-examples 500
   ```
   Watch `[train] step N/…` climb → ends `adapter saved -> …\finetune\adapter`.
2. **Export to GGUF:** `C:\train-venv\Scripts\python.exe -m Dev.kb_chatbot.finetune.merge_and_export --llama-cpp C:\llama.cpp`
3. **Serve:** `ai_pc\reasoning_gateway\07_activate_tuned.ps1` then `05_start_gateway.ps1`.
4. **Eval gate:** `... -m Dev.kb_chatbot.finetune.eval_compare --chroma "%LOCALAPPDATA%\ContosoKBChatbot\chroma" --eval-set Dev\kb_chatbot\finetune\eval_holdout.json --unsupported Dev\kb_chatbot\finetune\unsupported_questions.txt` (needs `ollama pull qwen2.5:3b-instruct` for the base comparison).
5. **Decide:** GATE PASS + good spot-check → keep. Else `08_rollback.ps1`.
6. If promising, the real run = same train command **without** `--max-examples` (and optionally `--seq-len 2048`), in a dedicated GPU window.

---

## 9. Hard-won gotchas (don't re-hit these)

- **Blackwell RTX 5060 Ti (sm_120)** needs **cu128** PyTorch + latest bitsandbytes; cu124's `is_available()` lies (warns sm_120 unsupported).
- **`apply_chat_template(tokenize=True)` returns TEXT here**, not tokens → tokenize with `tokenize=False` + an explicit `tokenizer(text)` call (already fixed in `train_qlora._encode`).
- **`device_map={"": 0}`** (not `"auto"`) — auto silently offloads to CPU and training crawls.
- **8 GB** → 3B not 7B; tail-truncate long examples to `seq_len`; levers `--seq-len`, `--max-examples`, `--epochs`, grad-accum.
- **Redaction gate** scrubs benign KB emails to `[redacted]` (was aborting the build).
- **`git pull` is unreliable here** (local-only repo, no shared remote) — deliver code by copying files/folder, and verify with `Select-String` before running.
- **OpenWolf post-write hook** occasionally rewrites `.wolf/anatomy.md` on non-`.wolf` edits — harmless; `git checkout .wolf/anatomy.md` if it churns.
