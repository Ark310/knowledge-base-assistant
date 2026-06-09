# KB Chatbot v2.6 — Design Spec

**Date:** 2026-06-09
**Status:** Approved
**Branch:** `feature/kb-chatbot-v2.6` (off current master = v2.5)
**Scope:** Four fixes/features in one release: (1) fix ChatGPT/Codex execution in the frozen exe + surface its errors, (2) accuracy — recalibrate the abstain floor + strengthen the answer prompt, (3) add support tickets as a PII-redacted retrieval source with clickable ticket/resolution references, (4) one-folder build for instant launch + offline bundled models + progressive load status.

**Explicitly out of scope:** the `dev/kb-chatbot-v3-retrieval-overhaul` branch (hybrid BM25/RRF/bge). It is abandoned for mainline and kept entirely separate per user decision — do NOT merge, port, or reference its modules. v2.6 uses only lightweight accuracy fixes.

---

## Context

The v2.5 exe was field-tested. Evidence gathered from `dist/chatbot_state/run.log` and `dist/chatbot_state/usage.jsonl`:

- **ChatGPT broke, Claude ran** (user-confirmed). `usage.jsonl` shows a `gpt-5.5` turn with `tokens_out: 1`, `latency_ms: 804` — Codex exited in 804 ms producing no text, and `CodexProvider` returned that blank as if successful because it discards `stderr`/return code.
- **Over-abstaining.** `run.log`: `Abstaining: top rerank score -1.334 < floor 0.300`. The reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) emits raw logits, but `CONFIDENCE_FLOOR = 0.30` was set as if scores were probabilities → valid answers are killed.
- **Weak/incomplete answers** (user-reported) — prompt under-instructs completeness.
- **Slow launch.** `.spec` is onefile (578 MB unpacked to `%TEMP%` every launch, pre-Python); ~50 HuggingFace network calls at startup (cache not offline); a 234 MB `claude_agent_sdk/_bundled/claude.exe` baked in by `collect_all`.

Ticket data now exists at `library/tickets/ticket_<id>.json` (+`.md`), 112 tickets. Schema: `title, product, organization, category, priority, assignee, status, severity, created_by, created_at, comments[], ticket_id, url, resolution_url, scraped_at`. `comments[]` holds the email/resolution thread and is **dense with customer PII** (names, emails, phones, company, signatures). Org policy: **never surface customer PII** — a hard constraint shaping the ticket design.

---

## 1. Fix ChatGPT/Codex in the frozen exe

### 1a. Stop swallowing failures (the real defect)

In `llm/codex_provider.py`, `_run_codex_exec` currently returns whatever text it scraped (empty on failure) and ignores `proc.returncode`/`proc.stderr`. Change it to:

- After `subprocess.run`, if `proc.returncode != 0` **or** the resolved answer text is empty: log `proc.returncode` and a truncated `proc.stderr` to `run.log` (NEVER the prompt — no PII/content logging), then raise a new `CodexExecError(RuntimeError)` with a concise reason (first ~300 chars of stderr, or "codex exec produced no output").
- The orchestrator's existing `except Exception` around `deps.llm.chat(...)` renders this as a visible assistant message ("Sorry — the LLM call failed: …") instead of a blank answer. (Optionally tighten the GUI/orchestrator message to name the provider.)
- `CodexNotFoundError` behaviour is unchanged.

This converts a silent blank into a diagnosable, user-visible error and writes the true cause to the log.

### 1b. Fix the frozen-exe-specific cause (evidence-driven)

After 1a is in, rebuild once, run the real exe, trigger a ChatGPT turn, and read the captured `stderr`/return code from `run.log`. Fix the specific cause it reveals. Leading hypotheses to confirm (do NOT pre-fix without the captured evidence):

- The windowed exe's working directory is a path with spaces (`…OneDrive - Contoso…`); `codex exec` may choke on cwd/sandbox. Candidate fix: pass an explicit safe working dir via `-C <tempdir>` (and keep `--skip-git-repo-check`).
- A `PATH`/env difference in the frozen subprocess affecting the `cmd /c codex.CMD` shim resolution.

Whatever the stderr names is fixed precisely; a regression test stubs the failure path (non-zero return / empty output → `CodexExecError`).

### Files
| File | Change |
|------|--------|
| `llm/codex_provider.py` | `CodexExecError`; `_run_codex_exec` checks returncode/empty, logs stderr, raises; targeted frozen-cause fix (e.g. `-C`) |
| `tests/test_codex_provider.py` | tests: non-zero return → raises; empty output → raises; stderr logged not prompt |

---

## 2. Accuracy — abstain floor + prompt

### 2a. Recalibrate the abstain floor (over-abstaining)

`retriever.py` gates on a raw CrossEncoder logit vs `CONFIDENCE_FLOOR = 0.30`. Change to normalize the top rerank score with a **sigmoid** (`1/(1+e^-logit)`) → 0–1 probability, and gate on a calibrated probability floor.

- Add `_sigmoid(x)` and apply it to `rerank_top_score` used for the abstain decision (store the normalized score on `RetrievalResult.rerank_top_score` so downstream — topic-drift, low-confidence footer — operate on the 0–1 scale; update those thresholds accordingly: drift floors and `LOW_CONFIDENCE_CEILING` are re-expressed on 0–1).
- New default `CONFIDENCE_FLOOR = 0.06` (≈ logit −2.75) — permissive enough to stop false abstains. **Empirically check** during implementation by replaying queries from `usage.jsonl` (records carry `retrieved_ids`): confirm known-good answers clear the floor and obvious misses fall below; adjust the constant if the replay shows otherwise. Document the chosen value.
- Backstop against bad-chunk hallucination is unchanged: the system prompt forbids non-context facts and requires citations, validated by `citations.py`. Loosening retrieval cannot cause hallucination — only fewer false "I don't have that."

**Downstream threshold updates (since the score scale changes to 0–1):** every consumer of `rerank_top_score` must move from the raw-logit scale to 0–1:
- `_DRIFT_PREVIOUS_FLOOR` / `_DRIFT_CURRENT_CEILING` and `LOW_CONFIDENCE_CEILING` in `orchestrator.py` re-expressed on the sigmoid scale (e.g. drift previous ≥ 0.85, current < 0.20; low-confidence ceiling 0.35).
- `config.CLARIFY_SCORE_FLOOR` (currently `-5.0`, a raw-logit value that is meaningless on 0–1) re-expressed to `0.0` so the abstain-path clarification check still triggers when appropriate (it remains gated by `_needs_clarification_from_quick`).
- All values confirmed against the `usage.jsonl` replay.

### 2b. Strengthen the answer prompt (weak/incomplete answers)

In `prompt.py` `SYSTEM_PROMPT`, keep all guardrails (context-only, citations, abstain phrase, one clarifying question) and add completeness directives:
- Synthesize across **all** relevant CONTEXT entries, not just the first.
- Include **every** step, parameter, and field present in the context for a procedure; preserve original ordering; never truncate a procedure mid-way.
- Prefer a complete, well-structured answer (numbered steps for procedures) over brevity.

No retrieval-cost change; prompt text only.

### Files
| File | Change |
|------|--------|
| `retriever.py` | `_sigmoid`; normalize rerank score; new floor default |
| `config.py` | `CONFIDENCE_FLOOR` 0.06 (+ comment on sigmoid scale) |
| `chat/orchestrator.py` | re-express drift + low-confidence thresholds on 0–1 |
| `prompt.py` | completeness directives in SYSTEM_PROMPT |
| `tests/` | `_sigmoid` mapping; abstain below/above floor on 0–1; drift/low-confidence threshold tests updated |

---

## 3. Tickets as a PII-redacted source

### 3a. Redaction (safety layer) — `chat/ticket_redactor.py` (new)

`redact(text: str, *, known_terms: list[str]) -> str` removes, conservatively:
- Email addresses, phone numbers, http(s) URLs embedded in signatures (regex).
- Email/quote boilerplate lines: `Subject:`, `To:`, `Cc:`, `attachment: … content-type: …`, legal/footer blocks, "Registered office", "Authorised by".
- `known_terms` (the ticket's own `organization`, `created_by`, `assignee`, and first-name tokens from `Hi <Name>` / `from <Name>` patterns) → replaced with `[redacted]`.
- When a line still looks like a signature/contact block after the above, drop it.

Returns cleaned text. Pure, no I/O. Heavily unit-tested against real samples (`ticket_75100`, `_75103`, `_75111`): assert output contains no `@`, no phone pattern, no `"Fabrikam Financial"`, no `"Sam"`.

### 3b. Ticket ingestion — `ticket_ingest.py` (new) + `ingest.py` wiring

- A `build_ticket_chunks(ticket_json, tickets_root)` produces chunks from each ticket:
  - **problem** = redacted first customer message (or `title` if none usable)
  - **resolution** = redacted staff comment(s) that closed it (heuristic: comments with `type == "comment"` and an internal `author`, especially the latest before `status: Closed`)
  - chunk text = `"<title>\n\nProblem: <problem>\n\nResolution: <resolution>"`
  - metadata: `kind: "ticket"`, `product` (mapped to existing product slugs where possible, else `"tickets"`), `ticket_id`, `title`, `url`, `resolution_url`, `category`.
- `ingest()` additionally walks `library/tickets/*.json` (sibling of `kb/`), redacts + chunks them, and upserts into the **same** ChromaDB collection. Tickets without a usable resolution are skipped (logged). The KB walk is unchanged.
- `config.py`: add `TICKETS_DEFAULT = BASE_DIR / "library" / "tickets"`.

### 3c. Retrieval, citation, prompt

- Tickets are normal chunks → retrieval/rerank/new floor apply unchanged.
- `citations.py`: a chunk with `kind == "ticket"` renders/validates as `[Ticket #<id> · <ProductDisplay>](resolution_url)`. URL-validated against retrieved chunks like any citation; falls back to `url` if `resolution_url` missing.
- `prompt.py`: context block labels ticket entries distinctly (e.g. `Ticket #75100 · TD Client Server`); add rule: *"CONTEXT may include past support tickets. If one resolved a similar issue, you may present its resolution and cite it as [Ticket #&lt;id&gt;](resolution_url). Never include customer names, emails, phone numbers, or company names — they are not in CONTEXT and must not be invented."*

### Files
| File | Change |
|------|--------|
| `chat/ticket_redactor.py` | **New** — `redact()` PII stripper |
| `ticket_ingest.py` | **New** — `build_ticket_chunks()` |
| `ingest.py` | walk + ingest `library/tickets/*.json` (redacted) |
| `config.py` | `TICKETS_DEFAULT` |
| `citations.py` | ticket citation form + validation |
| `prompt.py` | ticket labels in context + ticket rule |
| `tests/test_ticket_redactor.py` | **New** — PII never survives (real samples) |
| `tests/test_ticket_ingest.py` | **New** — chunk shape, metadata, resolution extraction, no-resolution skip |
| `tests/test_citations.py` | ticket citation parse/validate |

---

## 4. One-folder build + instant launch + offline models

### 4a. One-folder packaging

`ContosoKBChatbot.spec`: keep `Analysis`/`PYZ`/`EXE` but move `a.binaries, a.zipfiles, a.datas` out of `EXE(...)` and into a trailing `COLLECT(...)` so the result is a directory (`dist/ContosoKBChatbot/ContosoKBChatbot.exe` + support files). Launch becomes ~1 s (no self-extract). `build_chatbot_exe.bat` message updated; note distribution is now a folder/zip.

### 4b. Offline bundled models

- A tiny `runtime_hooks` script (or top-of-`gui.py`, before any `sentence_transformers`/`transformers`/`chromadb` import) sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_HOME` to a cache folder shipped inside the onedir build.
- The two model caches (`all-MiniLM-L6-v2`, `ms-marco-MiniLM-L-6-v2`) are added to the build via `datas` so they ship in the folder. Startup makes zero network calls.
- Fallback: if a model isn't found offline, catch and retry online once with a clear status message (so a broken bundle degrades, not crashes).

### 4c. Drop bundled-Claude bloat + use real CLI

- `.spec`: exclude `claude_agent_sdk/_bundled` from the collected datas/binaries (−234 MB).
- `llm/claude_code_provider.py`: when building `ClaudeAgentOptions`, pass `cli_path=shutil.which("claude")` (when found) so the app uses the user's authenticated `claude.EXE` deterministically in dev and frozen.

### 4d. Progressive load status

`InitWorker` already emits status; with the window now instant, wire explicit ordered messages through the existing `ThinkingIndicator`:
`✦ Starting…` → `✦ Loading search models…` → `✦ Warming up <provider>…` → status bar `Ready` + input unlock. No new threading; clearer per-stage text only.

### Files
| File | Change |
|------|--------|
| `ContosoKBChatbot.spec` | `COLLECT` (onedir); bundle model caches; exclude `_bundled` |
| `gui.py` (or runtime hook) | set HF offline env before model imports; clearer InitWorker stage text |
| `llm/claude_code_provider.py` | `cli_path=shutil.which("claude")` |
| `build_chatbot_exe.bat` | folder-output note |

---

## Versioning, Notes, Docs

- App version label → v2.6 (module docstrings / any version string).
- Update `MEMORY.md` pointer and `project_kb_chatbot_v23.md` with v2.6 summary + the documented fixes (Codex stderr-surfacing, sigmoid floor + chosen value, ticket redaction approach, onedir packaging, offline models, dropped bundled-claude).
- `.wolf/buglog.json` (OpenWolf): log the Codex-blank-on-failure bug, the logit-floor miscalibration, the onefile-unpack slowness, and the 234 MB bundled-claude bloat with root causes + fixes.

---

## Testing

- `test_codex_provider.py` — non-zero return raises `CodexExecError`; empty output raises; success path unchanged; stderr (not prompt) is what gets logged.
- `test_retriever.py` / new — `_sigmoid` maps logits to 0–1; abstain below floor, pass above, on the 0–1 scale.
- `test_orchestrator.py` — drift + low-confidence thresholds updated to 0–1; existing behavioural tests still green.
- `test_ticket_redactor.py` — emails/phones/orgs/names never survive on real samples.
- `test_ticket_ingest.py` — chunk text/metadata shape; resolution extraction; no-resolution skip.
- `test_citations.py` — ticket citation `[Ticket #id · Product](resolution_url)` parse + URL validation.
- Full suite green; then **live**: one real `codex exec` smoke test (verify the frozen-cause fix), one real retrieval query confirming a previously-abstained question now answers, and an exe launch confirming ~1 s window + offline (no network) startup.

---

## Out of Scope

- v3 retrieval overhaul (hybrid/BM25/RRF/bge) — abandoned for mainline, kept on its own branch/beta exe.
- NER-based name redaction — conservative regex + known-field redaction only; when uncertain, drop the line.
- Re-scraping tickets — uses the existing `library/tickets/` snapshot.
