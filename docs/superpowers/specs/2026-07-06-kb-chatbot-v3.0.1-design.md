# KB Chatbot v3.0.1 "KB Guru" — Accuracy Overhaul, 3-Provider Reasoning (incl. Fine-Tuned Local Model), Web-in-Desktop UI — Design Spec

**Date:** 2026-07-06
**Status:** Design approved (chat); pending spec review → implementation plan
**Builds on:** v2.9.2 (recency-bridging, cross-ticket same-error surfacing, FormFlow taxonomy, parent-document ticket reassembly, output PII scrub, 3-tier out-of-scope, enterprise Qt UI). v2.9.2 is COMPLETE on `feat/kb-chatbot-v2.9.2` (not merged, user's call).
**Target branch:** `feat/kb-chatbot-v3.0.1`

---

## 1. Context & Problem

v3.0.1 is a **major rebuild** with two thrusts the operator named after the last round of testing:

1. **Be the "Guru" for all Contoso products — accuracy, context-building, consistency.** v2.9.2 already added recency-bridging, cross-ticket same-error surfacing, and FormFlow taxonomy, but the *bridging / context-mapping / issue-classification* still feels weak and — most importantly — **inconsistent**. The tester's concrete consistency symptoms (confirmed this session) were:
   - **Same question, different answers** run-to-run (non-determinism).
   - **Rewording breaks it** — a slightly reworded question yields a much worse/different answer (phrasing sensitivity).
   - **Inconsistent answer format** — structure/length/tone varies a lot.
   - *(Notably NOT "inconsistent sources"* — the tester did **not** report that the wrong tickets/KB get surfaced, so this is a ranking-stability + generation-stability + formatting problem, not a "can't find the docs" problem.)

   The saved alpha logs in `Dev/kb_chatbot/state/chats/` illustrate the failure family: a follow-up like "who works on these / which client?" or a bare "ticket 75919" sometimes loses the prior focus or abstains even though the same ticket was just answered — and replaying the same conversation on a fresh build can behave differently. That run-to-run divergence is exactly the consistency complaint.

2. **Redesign the UI** to adopt the layout of Anthropic's `customer-support-agent` quickstart (settings/config at the top, side panels, clean chat), adapted to our extra functionality, keeping Contoso logos/branding and the versioned exe build.

Beyond those two, the operator expanded scope to the **runtime/reasoning architecture** — how the app runs, authenticates, and is distributed to colleagues — plus a **local, fine-tuned model** hosted on the in-house **AI PC**.

## 2. Goals

- **Consistency first.** The same question (and trivial rewordings of it) returns the same high-quality, identically-structured answer. Determinism where achievable; stabilization + caching where not.
- **Guru-grade accuracy.** Reliably classify an issue (product / issue-type / incident-vs-ticket), find its commonalities across tickets, comments, and incidents, and synthesize "what it is + how it was fixed + where it was seen (old↔new, dated) + who handled it" — every claim cited, abstain when unsure.
- **Three selectable reasoning providers**, user-picked per session: **Claude** (Claude Code CLI), **Codex/ChatGPT** (gpt-5.4 basic, *not* 5.5), and a **Local** model on the AI PC. Retrieval/classification run in the exe (CPU) and lift all three.
- **Distributable exe.** Fully-automatic first-run onboarding (dependency install + browser login) so a colleague can run the exe and self-provision.
- **A private, fine-tuned local guru.** A domain-adapted `qwen2.5-7b-instruct` served from the AI PC over an authenticated LAN gateway, provisioned per user.
- **Anthropic-style web UI** in a desktop shell, Contoso-branded, with chat history.
- **Current data.** Re-ingest the live `portal.contoso.example` portal, add **incidents** as a first-class type, and fix stale `support.contoso.example` citation URLs.
- **Enterprise-grade + thoroughly tested.** PII/secret redaction guarantees intact (including the training corpus); full test suite + an eval harness measuring accuracy *and* consistency; smoke + operator confirmation before every exe build.

## 3. Non-Goals

- **No embedding-model swap.** The current embedder (`all-MiniLM-L6-v2`) and cross-encoder reranker stay; the accuracy gain comes from **adding** BM25 + hybrid fusion + classification + determinism, not replacing the semantic model. (An embedder upgrade may be evaluated in a future version, gated on measured need.)
- **No change to the KYC model/project** on the AI PC. We add an **isolated** reasoning stack alongside it; KYC keeps its own model, prompts, data, route, and logs.
- **No API-key auth model.** Claude/Codex stay **account-based** (CLI + browser login); the local model uses **Basic auth** over the LAN gateway. No provider API keys stored.
- **No security regression.** The v2.9.1/v2.9.2 redaction + output-scrub guarantees stay; cloud providers receive only already-redacted context.
- **No abandonment of the offline retrieval story.** Embeddings/rerank/BM25/classification remain fully local in the exe.

## 4. Locked Decisions (from this brainstorm)

| Topic | Decision |
|---|---|
| Consistency symptoms to fix | Same-Q-different-answers, rewording-breaks-it, inconsistent-format. (Sources are already fine.) |
| Engine scope | **Realistic overhaul**: keep the embedder; **add BM25 hybrid retrieval + issue-classification + determinism + answer-format contract + an eval harness.** No embedder swap. |
| Providers | **All three selectable, user picks per session** (Claude, Codex gpt-5.4 basic, Local). No forced default. |
| Onboarding | **Fully automatic** (admin rights available): detect → silently install Node + CLI → browser login. **Guided-manual fallback** on any failure. |
| Local model | OpenAI-compatible **HTTP + Basic auth** to a **Caddy gateway** → localhost Ollama. Base **qwen2.5-7b-instruct**; served model name `contoso-reasoning-qwen25-7b`. **temp 0 + fixed seed** (true determinism). |
| Local accuracy strategy | **Fine-tune on our data** (both continued-pretraining on raw text **and** SFT on auto-generated QA pairs), **in this release**. |
| Training env | **Native Windows on the AI PC** (RTX 5060 Ti 8GB). QLoRA 4-bit; `qwen2.5-3b` fallback if 8B won't fit. |
| Training data | **Auto-generate QA pairs (operator spot-checks) + continued-pretraining on raw KB/ticket/incident text.** All training text redacted first. |
| Provisioning | **Per-user gateway credentials** (add/revoke individuals) stored in the app's OS keyring. |
| Data | **Re-ingest new `portal.contoso.example` + incidents (first-class) + fix stale URLs.** Reindex; bump schema. |
| UI | **Web-in-desktop-shell**, **QtWebEngine embedded in PySide6**, React/Tailwind, Anthropic-inspired. Panels: **top config bar + right Sources + left history + collapsible thinking/debug**. Drop "user mood." |
| Chat history | Stored **off OneDrive** (`%LOCALAPPDATA%`); list + search + rename + delete/export; **auto-name by ticket # → else topic**. |
| AI PC state | KYC already runs on the GPU via Ollama → driver risk retired; we only add our isolated model + gateway. |
| Version / build | **v3.0.1**, PyInstaller **one-folder** exe, ship prebuilt index (Chroma + BM25), Contoso branding. |
| Verification | Full suite + PII/secret probe (incl. training corpus) + eval accuracy&consistency + frozen-boot + live golden across all 3 providers → smoke + operator confirmation before compile. |

## 5. Architecture Overview

**Reused unchanged (the core):** `ingest`, `retriever` (embed + rerank + confidence gate), `chat/orchestrator`, `chat/ticket_redactor`, citation parse/validate, `ticket_ingest` chunking. Extended, not rewritten.

**Provider model — 3 selectable, retrieval shared:**

| Provider | Auth / install | Data location | Determinism | Role |
|---|---|---|---|---|
| **Claude** (`ClaudeCodeProvider`) | auto-install Node+CLI → browser login | cloud (redacted context only) | stabilized (not byte-identical) | max accuracy |
| **Codex/ChatGPT** (`CodexProvider`, gpt-5.4, reasoning=low) | auto-install Node+CLI → browser login | cloud (redacted context only) | stabilized | alternate |
| **Local** (`LocalProvider`, new) | LAN URL + per-user keyring creds | 100% on-prem | **true** (temp 0 + seed) | private, fine-tuned guru |

Embeddings + rerank + **BM25** + classification run **in the exe on CPU regardless of provider**, so all accuracy work benefits every provider.

**Phase sequence (one v3.0.1 release):**
1. Accuracy engine + eval harness → 2. Data refresh (incl. incident scraping) → 3. Reasoning backends + onboarding → 4. AI-PC runbook (parallel, on the AI PC) → 5. Fine-tune (needs 1, 2, 4) → 6. UI rebuild → 7. Package + ship.

## 6. Detailed Design

### 6.1 Phase 1 — Accuracy / "Guru" engine

**(a) Hybrid retrieval — `retriever.py`, `ingest.py`.** Build a **BM25 index** (`rank-bm25`, pure-Python, CPU, offline) from the same chunk corpus at ingest time, persisted alongside Chroma keyed to chunk ids + `CHUNK_SCHEMA_VERSION` (loaded at startup). Per query: take vector top-N *and* BM25 top-N, fuse with **Reciprocal Rank Fusion (RRF)**, then run the fused candidate set through the **existing cross-encoder reranker**. This preserves current semantic behavior and adds exact-term matching (ticket/incident #s, `GetWebDeal`, error codes, product names) — the fix for "rewording breaks it." RRF is deterministic; ties broken by chunk id.

**(b) Classification layer — new `chat/classifier.py`.** A deterministic per-query classifier producing: **product(s)** (via the existing synonym/`config.PRODUCTS` map), **issue-type** (error / how-to / config / incident), and **referenced ids** (regex for `ticket|bug|incident|#` + number). Deterministic → same query → same route → same retrieval → consistent answer. It drives product filtering and selects the answer template. Content is also classified at ingest (`kind ∈ {kb, ticket, incident}` + product + date).

**(c) Determinism — `retriever.py`, `chat/orchestrator.py`, new `chat/query_norm.py`, new `chat/answer_cache.py`.** (i) **Canonical query normalization** (lowercase, trim, collapse whitespace, synonym-fold) so trivial rewordings hit the same retrieval path. (ii) **Stable tie-breaking** by chunk id, fixed candidate counts. (iii) **Answer cache** keyed on `(normalized_query, provider, model, index_version)` → identical answer for a repeated question. **Honest limit:** true generation determinism (temp 0 + fixed seed) is achievable only on the **Local** provider; cloud CLIs (Claude/Codex) are *stabilized* (fixed retrieval + fixed prompt + low temp) and the answer cache closes the repeat-question gap — this is a design reason the local guru is the "consistent" one.

**(d) Answer-format contract — `prompt.py`.** A fixed output template, selected by issue-type, applied every time:
- **Summary** (1–2 sentences, cited)
- **Details / Steps** (numbered, each line cited)
- **Where seen** (tickets + incidents, dated, old↔new bridged) — for error/incident types
- **Recommended next step**
- **Sources**

Citation/abstain/CONTEXT-only guarantees unchanged; only the *shape* is pinned.

**(e) Eval harness — new `Dev/kb_chatbot/eval/`.** Grow `tests/fixtures/golden_qa.json` into a scored eval set (each case: question, expected source ids/keys, answer key-points). Two scores: **accuracy** (source recall + key-point coverage) and **consistency** (run each case K times; measure source-set stability + answer semantic-similarity variance). CLI runner produces a report per provider. This harness gates the fine-tune (§6.5) and is the release's proof.

### 6.2 Phase 2 — Data refresh

**(a) Re-ingest current portal — `ticket_ingest.py`, `citations.py`.** Point ticket ingestion at the **v4 scraper's `portal.contoso.example` output**; build citation URLs as `portal.contoso.example/tickets/{id}/edit`; add `portal.contoso.example` to the citation-validator host allow-list (keep `contoso.example`/`help.contoso.example` for legacy KB links that still resolve).

**(b) Incidents first-class — scraper + ingest.** Neither the scraper nor the chatbot handles incidents today (verified). Add an **Incident sub-view capture** to the v4 scraper (`scraper/parsers/` + `scraper/ticket_engine.py`, mirroring how Resolve/Files are captured — a `button.sidebar-menu-btn` "Incident" view, condition-based wait, DOM extraction) and an **incident chunk type** in ingest (`kind="incident"`, product + incident date metadata), so answers can say "seen as incident X and tickets Y, Z (dated…)".

**(c) State off OneDrive — `config.py`.** Move live `chatbot_state` (Chroma, chats, usage) to `%LOCALAPPDATA%\ContosoKBChatbot\` (freeze-aware), with one-time migration from the old path. Fixes the SQLite/Chroma corruption risk flagged by the AI-PC setup guide.

**(d) Reindex + schema bump — `config.CHUNK_SCHEMA_VERSION`.** Recency (`created_at`, added v2.9.2) extended to incidents. Full rebuild guarded by the existing "scan-first, abort-if-empty" logic.

### 6.3 Phase 3 — Reasoning backends + onboarding

**(a) Providers — `llm/`.** Keep `ClaudeCodeProvider`, `CodexProvider` (Codex pinned **gpt-5.4**, `reasoning_effort=low`, not 5.5). Add **`llm/local_provider.py`**: OpenAI-compatible HTTP (`/v1/chat/completions`) → `http://<SERVER_LAN_IP>:11500`, **Basic auth**, model `contoso-reasoning-qwen25-7b`, **temp 0 + fixed seed**, optional streaming. Register all three in `config.PROVIDERS`.

**(b) Fully-automatic onboarding — new `Dev/kb_chatbot/onboarding/`.** On the startup banner, per selected/needed provider: detect **Node.js** → silent install (winget or official installer) if missing; detect the **CLI** (`claude` / `codex`) → `npm i -g …` if missing; check login → launch **browser OAuth** (`claude` / `codex login`) if needed. Local: no install — test the gateway URL + creds, prompt + keyring-store if absent. **Every step has a guided-manual fallback** (link + copy-paste command) if silent install fails ("automatic, with a safety net"). Windows-focused.

**(c) Selection UI + security.** Provider/model selector + readiness dots in the top config bar (§6.6). Gateway URL + per-user creds in Settings (keyring). Redaction unchanged; cloud providers get scrubbed context only; credentials never logged (org policy).

### 6.4 Phase 4 — AI-PC runbook (on the AI PC; isolated from KYC)

Auto-implementable PowerShell + config under `C:\Contoso\LocalLLM_Setup\reasoning_chatbot\` (per the operator's existing `LocalLLM_Setup` guide, adapted to base `qwen2.5-7b-instruct` + per-user creds):

- **`01_install.ps1`** — verify Ollama (already GPU-working for KYC); `ollama pull qwen2.5:7b-instruct`; `ollama create contoso-reasoning-qwen25-7b -f Modelfile.reasoning`; set `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`; install Caddy.
- **`Modelfile.reasoning`** — `FROM qwen2.5:7b-instruct`, `temperature 0`, `num_ctx` sized for our prompts, chatbot-only SYSTEM prompt (no KYC assumptions). Swapped to the fine-tuned model after §6.5 passes its gate.
- **`Caddyfile`** — **multi-user** `basic_auth` block → `reverse_proxy 127.0.0.1:11434`, bound to `<SERVER_LAN_IP>:11500`.
- **`02_provision_user.ps1 <user>` / `03_deprovision_user.ps1 <user>`** — `caddy hash-password`, add/remove a user, reload gateway; the plaintext credential is emitted once for secure handoff, **never stored** in repo/OneDrive/logs.
- **`04_firewall.ps1`** — open TCP 11500 on the **Private** profile only.
- **`05_test.ps1`** — 401-on-bad-creds, 200-on-good-creds, a reasoning round-trip, `ollama ps` single-model check.
- **Wake-on-call** is native Ollama (loads on first request); `keep_alive` tuned to stay warm during use and free VRAM for KYC when idle. **KYC model/prompts/data/route untouched.**

**Delivery:** scripts + a short runbook the operator executes on the AI PC (or via a coding-agent later); this repo cannot run on that machine directly.

### 6.5 Phase 5 — Fine-tune (two-stage, eval-gated)

New `Dev/kb_chatbot/finetune/` (data pipeline) + on-AI-PC training:

- **Data.** **Stage A (continued-pretraining):** raw KB + ticket + incident text for domain fluency. **Stage B (SFT):** **auto-generated QA pairs** from KB articles + resolved tickets (question → grounded, cited answer), **generated via the Claude provider** (highest quality) and **operator spot-checks a sample** before training. **All training text passes through `ticket_redactor` first** — no customer PII/secrets enter the model (org policy). A `finetune/build_dataset.py` produces both corpora + a redaction-probe assertion (`leaks=0`).
- **Training (native Windows, RTX 5060 Ti 8GB).** **QLoRA 4-bit** (PEFT + transformers + bitsandbytes Windows wheels, or LLaMA-Factory), short training context + gradient accumulation to fit 8GB; **step 0 validates the toolchain** on a tiny run. Merge adapter → **GGUF** (llama.cpp) → `ollama create contoso-reasoning-qwen25-7b-ft`. **Fallback:** `qwen2.5-3b` if 8B training won't fit.
- **Gate.** The §6.1(e) eval harness scores fine-tuned vs base vs Claude on **accuracy + consistency**. **Promote the fine-tune only if it beats base** on the golden set; otherwise ship RAG-first on the base model and iterate — **no regression ships**.

### 6.6 Phase 6 — UI rebuild (web-in-desktop-shell)

**Architecture — `Dev/kb_chatbot/gui.py` (thin host) + `Dev/kb_chatbot/webui/` (React/Tailwind), `Dev/kb_chatbot/bridge.py`.** The PySide6 window embeds a **`QWebEngineView`** loading the **bundled local** built web UI (no remote content). Python ↔ JS over **`QWebChannel`**, exposing the engine: send/stream a message, list/search/rename/delete/export chats, switch provider+model, return the current answer's sources, run reindex, Learn Mode, settings. **All backend logic reused unchanged** — only presentation swaps.

**Layout (Anthropic-inspired, Contoso-branded):**
- **Top config bar** — Contoso logo; provider + model selector; product filter; per-provider readiness dots.
- **Left sidebar** — chat history: new chat, search, **auto-name (ticket # → else LLM topic title)**, rename, delete/export; collapsible.
- **Center** — message bubbles, streaming, markdown, inline citation links, attachments (existing).
- **Right sidebar** — **Sources** panel (tickets / KB / incidents behind the current answer: id, title, date, link) + collapsible **thinking/debug** panel (retrieval scores, classification, latency, tokens), hideable for regular users.

**Preserved:** Contoso palette/logos/splash/About; Learn Mode (PBKDF2); token-usage viewer; reindex/indexing progress (web modal via bridge signals); Settings. **Security:** local-only content + CSP; React escaping (no `dangerouslySetInnerHTML` on untrusted text) preserves the XSS guarantee; citations sanitized.

### 6.7 Phase 7 — Packaging + ship

- `APP_VERSION` → **3.0.1** (`config.py`; `tests/.../test_version.py`).
- **PyInstaller one-folder** (fresh `--workpath` per the OneDrive-lock lesson) bundling QtWebEngine resources + built web UI (`assets/webui/`) + models + **prebuilt index (Chroma + BM25)**; Contoso icon.
- Runtime state writes to `%LOCALAPPDATA%` (off OneDrive).
- Update `build_chatbot_exe.bat` + `ContosoKBChatbot.spec`.

## 7. Testing & Verification (every phase)

- **Unit/integration (pytest):** hybrid fusion (RRF order deterministic, BM25 recall for exact terms); classifier (product/issue-type/id extraction); query normalization; answer cache hit/miss; local provider HTTP + Basic-auth (mocked); onboarding detection/fallback (mocked installers); incident parse (fixtures); citation URL host allow-list; chat-history save/rename/auto-name/search; bridge API (mocked WebChannel); version = 3.0.1. **Full suite green.**
- **Security:** PII/secret probe `leaks=0` over the reindexed corpus **and the training corpus**; keyring-only creds; no plaintext credential in scripts/logs.
- **Eval harness:** accuracy + consistency scored per provider; consistency (same-Q + reworded-Q) demonstrably improved vs v2.9.2.
- **Live golden gate (all 3 providers):** an error question surfaces tickets + KB + incidents, dated old↔new; an FormFlow vs SalesHub question; a bare "ticket <id>" pin; a reworded pair returns equivalent answers.
- **AI-PC:** `05_test.ps1` passes (401/200, reasoning round-trip, single-model); KYC unaffected.
- **Build:** frozen-boot OK; state lands in `%LOCALAPPDATA%`; **smoke + operator confirmation before compile** (standing rule).

## 8. Risks & Mitigations

- **Cloud nondeterminism** (Claude/Codex can't be forced byte-identical) → fixed retrieval + fixed prompt + low temp + **answer cache**; the **local** model is the true-deterministic path. Documented, not hidden.
- **Auto-install fragility** (Node/global-npm) → guided-manual fallback per step; local provider needs no install at all.
- **8GB QLoRA of a 7B is tight** → short training context + grad accumulation + toolchain-validation step 0; `qwen2.5-3b` fallback.
- **Windows-native training toolchain finicky** → pinned Windows wheels / LLaMA-Factory; validated before the real run.
- **Fine-tune underperforms** → eval gate; ship RAG-first on base if it doesn't beat base (no regression).
- **QtWebEngine bloat (~150MB)** → accepted; one-folder build; only local content.
- **Incident scraping adds portal work + a re-scrape** → mirrors existing Resolve/Files capture; bounded.
- **Basic-auth-over-HTTP on the LAN** → private-profile firewall only; documented as LAN-testing posture, HTTPS/VPN the production upgrade path.
- **Reindex + re-scrape cost** → one-time at ship; scan-first guard prevents index wipe on empty source.
- **OneDrive locks during build/state** → fresh `--workpath`; runtime state moved off OneDrive.

## 9. Rollout / Sequencing Notes

Phases 1–2 (engine + data) land first (highest value, provider-independent). Phase 4 (AI-PC) runs in parallel on the AI PC. Phase 5 (fine-tune) depends on 1 (eval), 2 (data), 4 (machine). Phase 6 (UI) integrates provider selection from Phase 3. Phase 7 packages once all gates pass. Each phase gets its own implementation plan.
