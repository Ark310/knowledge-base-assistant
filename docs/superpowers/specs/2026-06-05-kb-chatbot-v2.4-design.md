# KB Chatbot v2.4 — Design Spec

**Date:** 2026-06-05
**Status:** Approved
**Branch:** `feature/kb-chatbot-v2.4`
**Scope:** Four enhancements — contextual retrieval with LLM rewrite escalation, thinking animation, Sonnet default model, token usage & cost viewer.

Approach C (full retrieval overhaul) is explicitly out of scope; its placeholder lives on `dev/kb-chatbot-v3-retrieval-overhaul` with scope notes.

---

## Context

v2.3 shipped multi-turn conversation, URL citations, instant startup, attachments, Learn Mode, and suggestions. Field use revealed two problems:

1. **Clarification context loss.** When the bot asks "which product?" and the user replies with a short answer ("TradeDesk"), that reply alone becomes the retrieval query. The original question is never re-searched, retrieval returns junk, and the accuracy rules force an abstain — the bot "loses the thread" despite having the conversation in memory. The same defect affects short follow-ups ("how do I reverse that?").
2. **Haiku default underperforms.** The default model is visibly weaker at synthesizing steps from context; failed rounds waste more tokens than a stronger model answering correctly once.

Verified Anthropic API pricing (platform.claude.com/docs/en/about-claude/pricing, June 2026): Haiku 4.5 = $1 in / $5 out per MTok; Sonnet 4.6 = $3 in / $15 out per MTok. The existing `config.COST_TABLE` already matches.

---

## 1. Contextual Retrieval + LLM Rewrite Escalation

### Layer 1 — Deterministic fusion (free, instant, always runs first)

In `chat/orchestrator.py`, before retrieval, build a **retrieval query** (distinct from the user message shown to Claude):

- **Clarification-answer fusion:** if the previous assistant turn has `kind == "clarification"`, the retrieval query becomes `<previous user question> <current reply>`. Additionally, if the current reply names exactly one product (case-insensitive match against `config.PRODUCTS`), apply it as a hard `Filters(product=...)` for this retrieval (unless the GUI filter is already set).
- **Short follow-up fusion:** if the current message has fewer than 5 words AND there is at least one prior user turn AND the previous-turn rule above didn't apply, the retrieval query becomes `<previous user question> <current message>`.
- Otherwise the retrieval query is the raw user message (today's behaviour).

The user message stored in the session and sent to Claude is always the raw message — fusion affects retrieval only.

### Layer 2 — Stateless LLM rewrite escalation

If retrieval (after fusion) **abstains** AND the session has at least one prior turn:

1. Make a single **stateless** call via the SDK's module-level `query()` function (NOT the persistent `ClaudeSDKClient` — a one-shot subprocess, so the chat session's history is never polluted). Model: Haiku (`claude-haiku-4-5-20251001`) for speed/cost regardless of the chat model.
2. Prompt: a short instruction to rewrite the user's latest message into a standalone knowledge-base search query, given the last 2 user/assistant exchanges. Output: the rewritten query only, max ~50 tokens.
3. Retry retrieval once with the rewritten query (same filters). If it now succeeds, proceed to the normal answer path; the context block comes from the rewritten-query retrieval, but the user message sent to Claude remains the raw message.
4. If it still abstains, fall through to the existing abstain-with-suggestions path (suggestions use the rewritten query, which is strictly better than the raw one).
5. Log the rewrite as its own usage record: `kind: "rewrite"`, model, tokens in/out, latency. Hard cap: at most ONE rewrite per turn.

New module: `chat/query_rewriter.py` — owns the rewrite prompt, the stateless SDK call, and a `RewriteResult(query, tokens_in, tokens_out, latency_ms)` return. The orchestrator depends on it via a `Deps.rewriter: Optional[Callable]` so tests stub it without subprocess calls.

Expected cost when escalation fires: ~300 tokens (~$0.0006) and ~2s — only on turns that would otherwise fail outright.

### Files

| File | Change |
|------|--------|
| `chat/query_rewriter.py` | **New** — stateless rewrite call + prompt |
| `chat/orchestrator.py` | Fusion logic; escalation path; product extraction from clarification replies; usage logging for rewrites |
| `chat/session.py` | Helper `last_user_question()` and `last_assistant_kind()` (read-only views over turns) |

---

## 2. Thinking Animation

### Per-question indicator

New widget `ThinkingIndicator(QLabel)` in `gui.py`:

- Visible only while a `TurnWorker` runs; sits directly under the chat view.
- Two `QTimer`s: word cycle every ~2,500 ms, dot pulse every ~400 ms (`…` grows/resets).
- Display format: `✦ <word><dots>` — italic, soft accent colour (`#7e57c2`), 10pt.
- Word pool, shuffled per turn: Pondering, Rummaging the KB, Connecting dots, Cross-referencing, Consulting the archives, Reticulating splines, Reading the manuals, Chasing citations, Untangling deals, Asking the librarian, Double-checking sources, Brewing an answer.
- When the Layer-2 rewrite fires, the orchestrator emits a progress signal and the indicator pins to `✦ Rephrasing your question for a better search…` until retrieval retries.
- Hidden the moment the turn finishes (success or failure).

`TurnWorker` gains a `progress = Signal(str)` so the orchestrator can surface the rewrite stage; `Deps` gains `on_progress: Callable[[str], None] = lambda s: None`.

### Startup loading state

The `InitWorker` status messages get the same treatment: the status-bar text is driven through the same `ThinkingIndicator` animation logic (a second instance bound to the status bar), cycling whimsical init words alongside the real stages:

- Stage 1 (models): `✦ Waking up the librarian…` / `✦ Stretching the neural nets…`
- Stage 2 (Claude warm-up): `✦ Warming up Claude…`

Input placeholder during init: `"Getting ready — one moment…"`.

### Files

| File | Change |
|------|--------|
| `gui.py` | `ThinkingIndicator` widget; wire to TurnWorker/InitWorker; progress signal plumbing |

---

## 3. Default Model → Sonnet

- `config.DEFAULT_MODEL = "claude-sonnet-4-6"`.
- One-time migration in `settings.py`: add field `model_explicitly_set: bool = False`. `SettingsDialog` saving sets it `True`. On load, if `model_explicitly_set` is `False` and the saved `default_model` is the old Haiku default, upgrade it to Sonnet; the GUI announces once: *"Default model upgraded to Sonnet for better accuracy — change it back anytime in the dropdown."*
- Haiku remains available in the dropdown and remains the model used for Layer-2 rewrites.

### Files

| File | Change |
|------|--------|
| `config.py` | `DEFAULT_MODEL` change |
| `settings.py` | `model_explicitly_set` field + migration in `load_settings` |
| `gui.py` | Migration announcement; SettingsDialog sets the flag |

---

## 4. Token Usage & Cost Viewer

### Entry point

`SettingsDialog` gains a **"View Token Usage…"** button at the bottom, opening `TokenUsageDialog`.

### Dialog content

**Summary (top):**
- All time: tokens in / out, estimated cost (from full `usage.jsonl` history)
- This session: same, filtered to records with `ts >=` app start time
- Per-query average: totals divided by count of LLM-calling records
- Query counts: all-time and session

**Table (middle, scrollable, newest first):** one row per usage record — Time, Kind (answer/rewrite/clarification/abstain), Model (display name), Tokens in, Tokens out, Cost. Zero-token rows (clarification/abstain without LLM call) show `$0.0000`.

**Footer:** `Rates: Haiku $1/$5 · Sonnet $3/$15 per MTok (API-equivalent) — Anthropic published pricing, June 2026` + Close button.

### Mechanics

- New module `usage_stats.py`: `load_usage(path) -> list[dict]`, `summarize(records, session_start) -> UsageSummary`, `cost_for(record) -> float`. Costs computed at display time from `config.COST_TABLE` so a rate edit reprices all history. Unknown models cost $0 with model name still shown.
- Malformed lines in `usage.jsonl` are skipped, never crash the dialog.
- The dialog is read-only; no network calls.
- Rewrite records (Section 1) and failed-auth records are present in the file; failed-auth rows (no tokens) are excluded from the table, rewrite rows are included.

### Files

| File | Change |
|------|--------|
| `usage_stats.py` | **New** — load/summarize/cost functions (pure, testable) |
| `gui.py` | Button in SettingsDialog; `TokenUsageDialog` (QTableWidget) |

---

## Summary of All File Changes

| File | Sections | Nature |
|------|----------|--------|
| `chat/query_rewriter.py` | 1 | **New** — stateless rewrite |
| `chat/orchestrator.py` | 1 | Fusion + escalation + progress callback |
| `chat/session.py` | 1 | Read-only history helpers |
| `usage_stats.py` | 4 | **New** — usage aggregation |
| `config.py` | 3 | Sonnet default |
| `settings.py` | 3 | `model_explicitly_set` migration |
| `gui.py` | 2, 3, 4 | ThinkingIndicator; migration notice; TokenUsageDialog |

**Unchanged:** retriever, chunker, ingest, citations, prompt, learn_writer, provider (the stateless rewrite lives in its own module).

---

## Out of Scope

- Hybrid search / BM25 / reranker upgrades → `dev/kb-chatbot-v3-retrieval-overhaul`
- Live pricing fetch — rates are hardcoded in `config.COST_TABLE`, edited manually when Anthropic's pricing changes
- Per-turn LLM rewriting — escalation-only by design (stateful-client constraint + latency)

---

## Testing Notes

- `test_query_fusion.py` — clarification fusion, product extraction → filter, short-follow-up fusion, raw passthrough; all pure orchestrator logic with stubbed retriever
- `test_query_rewriter.py` — prompt construction; orchestrator escalation path with stubbed rewriter (fires only on abstain-with-history, max once, logs usage, suggestions use rewritten query)
- `test_usage_stats.py` — load/skip-malformed, summarize windows, cost computation per model, unknown-model handling
- `test_settings.py` extension — `model_explicitly_set` migration matrix (unset+haiku→sonnet; explicit haiku stays; sonnet stays)
- GUI animation: no unit tests (Qt timers); verified in manual walkthrough
