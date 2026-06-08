# KB Chatbot v2.5 — Design Spec

**Date:** 2026-06-08
**Status:** Approved
**Branch:** `feature/kb-chatbot-v2.5`
**Scope:** Add OpenAI/ChatGPT as a second selectable AI provider alongside Claude, via the Codex CLI subprocess (account-based, no API key). New AI Provider dropdown, per-provider model selection, provider-aware cost accounting in the token viewer, and in-window notices on provider/model change.

---

## Context

The chatbot reaches Claude through the **Claude Code CLI subprocess** (`claude` binary, via `claude-agent-sdk`) — no API key, riding the user's Claude subscription. OpenAI has a direct analog: the **Codex CLI** (`codex` binary, v0.130.0 verified on the user's machine), authenticated with the user's ChatGPT account via `codex login`. So ChatGPT is added the same way Claude works today: a subprocess provider, no API key, no per-token billing.

v2.3 left a clean `LLMProvider` ABC (`llm/base.py`) with a single `chat(*, messages, model, system_prompt, max_tokens)` method and a model-keyed `COST_TABLE`. v2.5 adds a sibling provider and makes the GUI/config provider-aware. The retrieval core, orchestrator pipeline, citations, prompt, Learn Mode, attachments, and token-viewer machinery are reused unchanged except where noted.

### Verified facts (do not re-derive)

**Codex `exec` non-interactive invocation** (from `codex exec --help`):
- `-m, --model <MODEL>` — model selection
- `[PROMPT]` positional or `-` to read from stdin
- `-i, --image <FILE>` — repeatable image attachments
- `--json` — emit JSONL events on stdout
- `-o, --output-last-message <FILE>` — write the final assistant message to a file
- `-s, --sandbox read-only` / `--skip-git-repo-check` / `--ephemeral` — safe, repo-independent, no persisted session
- `codex login status` — auth check (account-based)

**Codex `exec --json` event shapes** (captured from a real run):
```
{"type":"thread.started","thread_id":"..."}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"<ANSWER>"}}
{"type":"turn.completed","usage":{"input_tokens":65608,"cached_input_tokens":2432,"output_tokens":19,"reasoning_output_tokens":12}}
```
- Answer text: the `-o` file (clean); fallback = `item.completed` event where `item.type == "agent_message"`.
- Usage: the `turn.completed` event's `usage` object.
- **Codex injects a large agent scaffold** — even a trivial prompt reported ~65k input tokens. ChatGPT queries will therefore show much higher token counts and API-equivalent cost than Claude. This is real and surfaced honestly (see §4).
- `--json` events are on **stdout**; unrelated `ERROR ... failed to load skill` lines (a pre-existing Codex config quirk) go to **stderr** and are ignored. Lines on stdout that don't parse as JSON are skipped defensively.

**Current OpenAI models via ChatGPT-subscription Codex + verified API-equivalent pricing** (openai.com/api/pricing, June 2026):
| Model | Tier | $/MTok in | $/MTok out |
|-------|------|-----------|------------|
| `gpt-5.5` | smartest (Codex default for ChatGPT auth) | 5.00 | 30.00 |
| `gpt-5.4` | mid / fallback | 2.50 | 15.00 |
| `gpt-5.4-mini` | fast / cheap | 0.75 | 4.50 |

---

## 1. CodexProvider

New file `Dev/kb_chatbot/llm/codex_provider.py` implementing `LLMProvider`.

### Invocation

Each `chat()` builds and runs (via `subprocess.run`, `CREATE_NO_WINDOW` on Windows mirroring the Claude provider's hidden-window patch):

```
codex exec -m <model> --json --sandbox read-only --skip-git-repo-check --ephemeral -o <tempfile> -
```

The flattened prompt is written to the process's **stdin** (the trailing `-`), avoiding command-line length/quoting limits. Image attachments add repeatable `-i <tempfile>` flags.

### Prompt construction (stateless flatten)

`codex exec` is stateless per call, so `CodexProvider.chat()` flattens the **entire** `messages` list into one prompt: the `system_prompt` first (as a leading instruction block), then each prior turn role-tagged, then the final user block (context + question). Helper `_flatten_messages(system_prompt, messages)`. This differs from `ClaudeCodeProvider`, which sends only the latest message because its SDK client is stateful — each provider correctly interprets the shared `messages` interface for its transport. The orchestrator is unchanged.

### Output parsing

- Read the `-o` tempfile for the answer text. If empty, fall back to scanning stdout JSONL for the last `item.completed` event with `item.type == "agent_message"` and take its `text`.
- Parse stdout line by line; `json.loads` each line in a try/except (skip non-JSON). From the `turn.completed` event's `usage`:
  - `input_tokens` → `LLMResponse.input_tokens` (full count, including Codex scaffold — honest)
  - `output_tokens + reasoning_output_tokens` → `LLMResponse.output_tokens` (reasoning tokens are billable output)
- If no usage event is found, fall back to `len(prompt)//4` / `len(text)//4` estimates (same machinery as Claude).
- `cost_estimate_usd` via the shared `estimate_cost(model, in, out)`.

### Errors

`CodexNotFoundError(RuntimeError)` (mirrors `ClaudeCodeNotFoundError`). Raised by a `_ensure_codex_available()` preflight: `shutil.which("codex")` missing → not installed; `codex login status` nonzero/"not logged in" → not authenticated. Message names the exact fix (`install Codex CLI` / `run 'codex login'`). The orchestrator already catches provider errors and renders them as an in-chat abstain, so a missing/unauthenticated Codex never crashes a turn.

### Temp files

Prompt stdin needs no temp file. The `-o` output file and any image temp files are created under the system temp dir and deleted in a `finally`. A reusable `_run_codex_exec(prompt, model, image_paths) -> (text, in_tok, out_tok)` helper centralises subprocess logic so the rewriter (§4) reuses it.

### warm_up / shutdown

`warm_up(system_prompt, model)` is a no-op aside from an optional cached `_ensure_codex_available()` (exec is cold-start per call; nothing persistent to boot). `shutdown()` is a no-op. This keeps `InitWorker` provider-agnostic.

### Files

| File | Change |
|------|--------|
| `llm/codex_provider.py` | **New** — `CodexProvider`, `CodexNotFoundError`, `_run_codex_exec`, `_flatten_messages` |

---

## 2. Provider Registry + Cost Table (`config.py`)

Restructure model config into a provider registry:

```python
DEFAULT_PROVIDER = "claude"

PROVIDERS = {
    "claude": {
        "display": "Claude",
        "default_model": "claude-sonnet-4-6",
        "models": {
            "Haiku (fast / cheap)": "claude-haiku-4-5-20251001",
            "Sonnet (smarter)":     "claude-sonnet-4-6",
        },
    },
    "openai": {
        "display": "ChatGPT",
        "default_model": "gpt-5.5",
        "models": {
            "GPT-5.5 (smartest)":  "gpt-5.5",
            "GPT-5.4 (mid)":       "gpt-5.4",
            "GPT-5.4-mini (fast)": "gpt-5.4-mini",
        },
    },
}

# Backward-compatible aliases (Claude provider) so existing imports keep working
DEFAULT_MODEL    = PROVIDERS["claude"]["default_model"]
AVAILABLE_MODELS = PROVIDERS["claude"]["models"]
```

`COST_TABLE` gains the OpenAI rows:
```python
"gpt-5.5":      {"in": 5.00,  "out": 30.00},
"gpt-5.4":      {"in": 2.50,  "out": 15.00},
"gpt-5.4-mini": {"in": 0.75,  "out": 4.50},
```

New `MODEL_DISPLAY` (model id → short label), replacing the token viewer's hardcoded two-entry dict:
```python
MODEL_DISPLAY = {
    "claude-haiku-4-5-20251001": "Haiku",
    "claude-sonnet-4-6":         "Sonnet",
    "gpt-5.5":                   "GPT-5.5",
    "gpt-5.4":                   "GPT-5.4",
    "gpt-5.4-mini":              "GPT-5.4-mini",
}
```

Helpers: `models_for(provider_id) -> dict[label,id]`, `default_model_for(provider_id) -> str`, `provider_of_model(model_id) -> Optional[str]` (used by the load-time validation guard in §5).

### Files

| File | Change |
|------|--------|
| `config.py` | Provider registry, derived aliases, OpenAI cost rows, `MODEL_DISPLAY`, helper functions |

---

## 3. GUI — AI Provider Dropdown, Notices, Preflight

### Layout

A new **AI Provider** `QComboBox` (`self.provider_box`) immediately left of the Model dropdown in the filter row, populated from `config.PROVIDERS` (display → provider id).

### Model repopulation

`_on_provider_changed(provider_id)`:
- Block the model box's signals, clear it, refill from `config.models_for(provider_id)`, select that provider's `default_model`, unblock.
- Post the combined provider-switch notice (below).

A `_populate_model_box(provider_id, select_model=None)` helper is shared by init and provider-change.

### In-window change notices

Both dropdowns post a muted-accent system line via the existing `_append("system", …)`:
- Provider switch → `⇄ Switched to ChatGPT — model set to GPT-5.5`
- Model-only change → `⇄ Model changed to GPT-5.4-mini`

Guard: notices fire on real user changes, not on programmatic repopulation (use `blockSignals` during `_populate_model_box`, and an `_initialised` flag so the initial population is silent).

### Provider construction in `_send`

Replace the hardcoded `llm = ClaudeCodeProvider()` with a factory:

```python
def build_provider(provider_id: str) -> LLMProvider:
    if provider_id == "openai":
        return CodexProvider()
    return ClaudeCodeProvider()
```

`_send` reads `provider_id = self.provider_box.currentData()` and `model = self.model_box.currentData()`, builds the matching provider, and wires `deps.rewriter = make_rewriter(provider_id)` (§4). Both `ClaudeCodeNotFoundError` and `CodexNotFoundError` are caught and rendered as the same friendly install/login chat message.

### Preflight & init

- Startup preflight stays for the default provider. `main()`'s existing `_preflight_claude_code()` becomes `_preflight_provider(default_provider)` — checks `claude` or `codex login status` depending on the saved default. A missing default-provider CLI shows a blocking dialog with the exact fix (unchanged UX, now provider-aware).
- On first switch to a provider whose CLI is unverified this session, a lightweight readiness check runs; failure locks input with a clear message instead of failing mid-query.
- `InitWorker` warms whichever provider is the current default (Codex warm-up = no-op/login probe).

### Token-viewer footer

Generalize `TokenUsageDialog`'s footer from "Anthropic published pricing" to:
`Rates: API-equivalent, Anthropic & OpenAI published pricing (June 2026). ChatGPT counts include Codex's agent overhead. Edit config.COST_TABLE if rates change.`

### Files

| File | Change |
|------|--------|
| `gui.py` | AI Provider dropdown; `_on_provider_changed`/`_populate_model_box`; change notices; `build_provider`; provider-aware preflight; init from saved provider; footer text |

---

## 4. Provider-Aware Rewriter + Multi-Turn

### Multi-turn

The orchestrator is unchanged and provider-agnostic. Claude reads the latest message (stateful client); Codex flattens the full `messages` (stateless, §1). v2.4 fusion + topic-drift apply identically for both.

### Rewrite escalation factory

The v2.4 escalation (`query_rewriter.rewrite_query`) is Claude-hardwired. v2.5 adds `make_rewriter(provider_id) -> Callable[[str, list], Optional[RewriteResult]]`:
- `claude` → existing Claude Haiku one-shot (`rewrite_query`, unchanged).
- `openai` → new `rewrite_query_codex`: a one-shot `codex exec` with **gpt-5.4-mini**, reusing `CodexProvider._run_codex_exec`. Same `REWRITE_SYSTEM_PROMPT`/`build_rewrite_prompt`/`_clean_response` are shared (kept provider-neutral). Returns the same `RewriteResult`. On any failure returns `None` (escalation is best-effort; never breaks a turn).

`RewriteResult` gains a field `model: str = ""` so the result carries the model that actually ran. Each rewrite path sets it (`claude-haiku-4-5-20251001` or `gpt-5.4-mini`). The default keeps existing 4-arg constructions in tests valid.

`_send` wires `deps.rewriter = make_rewriter(provider_id)`. The orchestrator logs the `kind="rewrite"` usage record with `model=rw.model` (falling back to `_REWRITE_MODEL_NAME` only if `rw.model` is empty), so the token viewer attributes the rewrite's cost to the provider that actually ran it.

### Files

| File | Change |
|------|--------|
| `chat/query_rewriter.py` | `RewriteResult.model` field; `make_rewriter(provider_id)`; `rewrite_query_codex`; Claude path sets `model`; shared prompt/clean helpers stay provider-neutral |
| `chat/orchestrator.py` | Log rewrite Turn with `model=rw.model or _REWRITE_MODEL_NAME` |

---

## 5. Settings Persistence + Migration

`Settings` gains `default_provider: str = "claude"`.

### Loading

`load_settings` reads `default_provider` (default `"claude"` when absent — existing v2.4 files keep current behaviour). Validation guard: if `config.provider_of_model(default_model) != default_provider` (corrupt/hand-edited pairing), reset `default_model` to `config.default_model_for(default_provider)` so dropdowns never initialise invalid.

### SettingsDialog

The dialog's single "Default model" combo becomes a **Provider + Model pair** mirroring the main window (provider change repopulates the model list). `values()` returns `Settings(..., default_provider=<picked>, default_model=<picked>, model_explicitly_set=True, learn_mode_hash=self._current.learn_mode_hash)`. The v2.4 `model_explicitly_set` flag and `learn_mode_hash` round-trip untouched.

### Migration

v2.4's `migrate_default_model` (implicit Haiku→Sonnet, Claude-only) is unchanged and still runs. v2.5 adds no forced migration: a missing `default_provider` resolves to Claude, so a v2.4→v2.5 upgrade is seamless (same provider, same model) with ChatGPT now available in the dropdown.

### Main-window init

On startup, set `provider_box` from `settings.default_provider`, populate `model_box` for that provider (silently), then select `settings.default_model`.

### Files

| File | Change |
|------|--------|
| `settings.py` | `default_provider` field; load + validation guard |
| `gui.py` | SettingsDialog Provider+Model pair; init from saved provider (covered in §3) |

---

## Summary of File Changes

| File | Sections | Nature |
|------|----------|--------|
| `llm/codex_provider.py` | 1 | **New** — Codex subprocess provider |
| `config.py` | 2 | Provider registry, OpenAI costs, display map, helpers |
| `gui.py` | 3, 5 | Provider dropdown, notices, factory, preflight, SettingsDialog pair |
| `chat/query_rewriter.py` | 4 | Provider-aware rewriter factory + Codex rewrite |
| `chat/orchestrator.py` | 4 | Confirm rewrite-model logging uses reported model |
| `settings.py` | 5 | `default_provider` + validation |

**Unchanged:** retriever, chunker, ingest, citations, prompt, learn_writer, session, usage_stats (cost_for already works for any COST_TABLE key), claude_code_provider.

---

## Out of Scope

- OpenAI API-key path — explicitly account-based (Codex CLI) only, mirroring Claude. No key is ever stored, logged, or committed.
- Additional providers (Gemini, etc.) — registry makes them easy later, but YAGNI now.
- Streaming responses, Codex session resume / multi-turn-via-resume — stateless flatten is sufficient.
- Reducing Codex's agent-scaffold token overhead — it's inherent to `codex exec`; surfaced honestly, not optimized.

---

## Testing Notes

- `test_codex_provider.py` — `_flatten_messages` (system + history + latest ordering); stdout JSONL parsing (answer from `-o` file; usage from `turn.completed`; `output = output_tokens + reasoning_output_tokens`; non-JSON/stderr lines skipped); estimate fallback when no usage event; `CodexNotFoundError` when binary absent. Subprocess itself is stubbed/monkeypatched — no real `codex` calls in tests.
- `test_config_providers.py` — registry integrity (every model in PROVIDERS has a COST_TABLE row and a MODEL_DISPLAY label); `models_for`/`default_model_for`/`provider_of_model`.
- `test_query_rewriter.py` extension — `make_rewriter("claude")` returns the Claude path; `make_rewriter("openai")` returns the Codex path; both honour the `Optional[RewriteResult]` contract (stubbed).
- `test_settings.py` extension — `default_provider` round-trip; validation guard resets a mismatched model; missing key → "claude".
- GUI (provider dropdown, repopulation, notices) — no Qt unit tests; verified in the manual walkthrough (provider switch posts notice; model list changes; ChatGPT answers; token viewer shows GPT rows with cost).
