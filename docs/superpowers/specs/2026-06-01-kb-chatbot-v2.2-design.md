# Design: KB AI Chatbot V2.2 — Claude Code Auth + New Library + Crash Fix
**Date:** 2026-06-01
**Status:** Approved design; pending implementation
**Supersedes UI/auth/data sections of:** `2026-05-28-kb-ai-chatbot-design.md` (V2.1). RAG architecture, citation safety contract, GUI shell, and threading model are unchanged.

---

## Why V2.2

Three concrete problems with the V2.1 build:

1. **Crash at launch.** The PyInstaller spec excluded `torch.cuda`, but PyTorch's C extension imports `torch.cuda` unconditionally at startup. Fix: drop the exclusion. (Other torch sub-packages — `torchvision`, `torchaudio`, `torch.distributed` — stay excluded; those are unused.)

2. **Wrong auth model.** V2.1 asks each user for an Anthropic API key. The user wants the chatbot to use their existing Claude Code subscription instead (no separate API spend). Fix: replace the Anthropic SDK provider with a `ClaudeCodeProvider` built on the `claude-agent-sdk` Python package, which programmatically invokes the locally-installed `claude` CLI and uses its existing OAuth. **The API-key path is removed entirely.** Every teammate installs Claude Code (free) and logs in once; the chatbot then "just works" with no key entry.

3. **Library structure changed.** The KB has been re-scraped into `library/kb/` with **1,466 articles across 6 products** (api 692 · tradedesk 501 · other 116 · web2 97 · saleshub 43 · web4 17). Schema per article is now flat: `{title, space_key, space_name, product, url, scraped_at, screenshot, body_md}`. The current chunker (which expects `enhancements/bugs/tasks/schema_changes` arrays) cannot read it.

Plus a small refinement based on the user's feedback: when the chatbot doesn't have an answer, it must say "I haven't been trained on this — it's not in the knowledge base" rather than guess. This is already the V2.1 strict-abstain behaviour, but the wording will be reinforced in the system prompt and the abstain template.

---

## Scope (what changes vs V2.1)

| Area | V2.1 | V2.2 |
|---|---|---|
| LLM auth | Anthropic API key via keyring | Claude Code subprocess via `claude-agent-sdk`; no key |
| Library path | `<base>/library` | `<base>/library/kb` |
| Article schema | per-version JSON with sections | per-article JSON with `body_md` markdown |
| Chunker | row-based + version chunk | markdown-aware semantic chunks of `body_md` |
| Products | `tradedesk / web4 / saleshub` (3) | `api / tradedesk / saleshub / web2 / web4 / other` (6) |
| Citation format | `[Product Version · section · TFS-id]` | `[Product · Category · Article title]` |
| System prompt | "release notes" focus | "knowledge base" focus + stronger abstain wording |
| Ambiguity check | dominant ratio ≥ 60% | unchanged threshold, but stricter trigger (6 products = more ambiguity) |
| PyInstaller excludes | included `torch.cuda` (broken) | `torch.cuda` removed; keep `torchvision`, `torchaudio`, `torch.distributed` |
| Settings dialog | API key + library path + model | library path + model only (no key field) |
| First-run UX | "Paste API key" dialog | "Verifying Claude Code…" check + clear error if missing |

Unchanged: GUI shell, threading model (`Worker(QThread)`, `SignalBridge`, `Retriever.close()` pattern), local sentence-transformers embeddings, ChromaDB store, cross-encoder rerank, confidence gate, citation validator, session persistence, run.log + usage.jsonl.

---

## Component changes

### `config.py`
- `LIBRARY_DEFAULT = BASE_DIR / "library" / "kb"`.
- `PRODUCTS = ("api", "tradedesk", "saleshub", "web2", "web4", "other")`.
- `PRODUCT_DISPLAY = {"api": "API", "tradedesk": "TradeDesk", "saleshub": "SalesHub", "web2": "Web2", "web4": "Web4", "other": "Other"}`.
- Remove `KEYRING_SERVICE` / `KEYRING_USERNAME`.
- Remove `COST_TABLE` (Claude Code subprocess doesn't surface per-call USD; we record `tokens_in/out` and let the user infer cost from their Claude plan).
- Add `CLAUDE_CODE_MODEL = "claude-haiku-4-5-20251001"` (default); `AVAILABLE_MODELS` kept.

### `settings.py`
- Remove `get_api_key`, `set_api_key`, `clear_api_key`. Remove the `keyring` import.
- `Settings` keeps `library_path`, `default_model`, `confidence_floor`. JSON round-trip unchanged.

### `chunker.py` (rewrite)
- New `Chunk` shape unchanged: `{id, text, metadata}`.
- New `build_article_chunks(article_data: dict, target_tokens: int = 500) -> list[Chunk]`:
  - Pull `title`, `product`, `space_key`, `space_name`, `url`, `body_md`.
  - Derive `category` from the article's file path (e.g., `library/kb/tradedesk/dealing/foo.json` → `category="dealing"`). Helper `_category_from_path(path)`; the ingestor passes the path.
  - Split `body_md` into chunks targeting ~500 words. Algorithm: prefer splits at `##`/`###` headings; for sections that exceed the target, sub-split on paragraph boundaries (`\n\n`). Never split inside a code block or table row. Output `text` includes the article title + a short breadcrumb so a chunk read in isolation makes sense (`"TradeDesk · dealing · {title}\n\n{chunk body}"`).
  - Chunk ID: stable hash of `(space_key, title, chunk_index)` so reindexing is idempotent.
  - Metadata: `{kind: "article", product, category, space_key, space_name, title, url, chunk_index, md_path}`.
- Drop `build_row_chunks`, `build_version_chunk`, `ROW_SECTIONS` — they don't apply.

### `ingest.py`
- Walks `<library>/<product>/**/*.json` (any depth, not just `versions/`).
- Skips files that don't have a `body_md` field (safety against stray files).
- Skips `index.json` and `index.md` at the library root.
- Reports per-product article counts + total chunk count.
- Otherwise unchanged: ChromaDB persistence, batch embeddings, `client.close()`.

### `retriever.py`
- Unchanged interface. The product filter dropdown in the GUI gets six options instead of three; that's plumbing.

### `prompt.py`
- Updated `SYSTEM_PROMPT`. Locked text (final, will be asserted in tests):

> You are the Contoso Knowledge Base Assistant. You answer questions about the Contoso KB articles — release notes, how-to guides, API references, and product documentation for TradeDesk, Web2, Web4, SalesHub, and the API.
>
> Hard rules — no exceptions:
> 1. You may only use facts from the CONTEXT block below. You have no other knowledge of Contoso products. Do not use general knowledge, intuition, or assumptions.
> 2. If the answer is not in the context, reply exactly: "I haven't been trained on this — it's not in the knowledge base I have access to. Want to refine the question?" — and offer one specific refinement (different product, related keyword, a how-to topic). Never invent.
> 3. Every factual claim must end with a citation tag in this exact form: `[<Product> · <Category> · <Article title>]` — e.g. `[TradeDesk · dealing · Booking a Spot Deal]`. A claim without a valid citation is forbidden.
> 4. If the user's intent is ambiguous (could refer to multiple products, multiple topics, or a vague feature name), do not answer. Instead, ask exactly one clarifying question.
> 5. Format the answer as: one-sentence direct answer first; then bullet list of relevant items (each with citation); then a "Searched:" footnote naming the product(s) and category you considered.
>
> Do not editorialise. Do not apologise. Do not speculate about features that aren't documented. Do not summarise articles that weren't retrieved.

- `format_context` updates the cite handle format to `[Product · category · Title]`.
- `_PRODUCT_DISPLAY` and `_CATEGORY_DISPLAY` are config-driven.

### `citations.py`
- Regex updates to the new format. Capture groups: `product`, `category`, `title`.
- Validation compares `(product, category, title)` against retrieved chunk metadata. Title-equality is case-sensitive trimmed; category is matched case-insensitively because the display vs slug forms might differ slightly.
- `[unverified]` substitution behaviour unchanged.

### `llm/claude_code_provider.py` (new — replaces `anthropic_provider.py`)
- Uses `claude-agent-sdk` Python package.
- `ClaudeCodeProvider(LLMProvider)`:
  - Constructor verifies the `claude` CLI is on PATH (`shutil.which("claude")`); raises a clear `RuntimeError` with installation guidance if not found.
  - `chat()` runs the async `query(prompt=..., options=ClaudeAgentOptions(system_prompt=..., model=...))` in a fresh event loop (we're on a Qt worker thread, so spinning up `asyncio.run()` per call is fine; one LLM call per turn).
  - Collects text blocks from the streamed messages, accumulates them, returns `LLMResponse(text, input_tokens, output_tokens, model, latency_ms, cost_estimate_usd=0.0)`.
  - When the SDK exposes usage metadata, we capture it; if not, we estimate via `len(text)/4` as a fallback.
- `llm/fake_provider.py` stays (used by tests).
- `llm/anthropic_provider.py` deleted.
- `llm/__init__.py` updated to import `ClaudeCodeProvider` only.

### `chat/orchestrator.py`
- Default model constant updated to `CLAUDE_CODE_MODEL`.
- Catches a specific `ClaudeCodeNotFoundError` (raised by the provider when the CLI isn't on PATH) and surfaces the actionable message to the GUI: "Claude Code isn't installed or not on PATH. Install from https://claude.com/claude-code and run `claude login` once."
- Abstain template updated to match the new system prompt's locked phrase.

### `gui.py`
- Settings dialog drops the API-key row entirely.
- First-run flow: on app open, if `shutil.which("claude")` returns `None`, show a blocking modal with installation guidance, then close. Otherwise proceed normally.
- Status footer drops `cost_estimate_usd`; shows queries + tokens only (cost lives in the user's Claude plan dashboard).
- Product filter dropdown has six options (Any + 5 named + Other).

### `ContosoKBChatbot.spec`
- Remove `torch.cuda` from `excludes`. Keep `torchvision`, `torchaudio`, `torch.distributed` excluded.
- Add `claude-agent-sdk` to `collect_all` packages.
- Drop `anthropic` and `keyring` from `collect_all`; remove `keyring` from `hiddenimports` if listed.

### `requirements.txt`
- Add: `claude-agent-sdk>=0.1.0`.
- Remove: `anthropic`, `keyring`.

---

## First-run UX (new)

1. User double-clicks `dist\ContosoKBChatbot.exe`.
2. App checks `claude` CLI is on PATH.
   - **If missing:** blocking dialog: "Claude Code is required. Install from https://claude.com/claude-code, run `claude login`, and re-launch this app." → close.
   - **If present:** continue.
3. App checks ChromaDB index existence at `<state>/chroma/`.
   - **If missing or library mtime is newer:** non-blocking banner "Index is out of date — click Reindex to update." User clicks Reindex; ingest runs for 5–10 minutes against the 1,466-article library.
   - **If present and current:** ready immediately.
4. User asks questions. Each LLM call goes through `claude-agent-sdk` → local `claude` CLI → uses the user's existing Claude Code OAuth.

---

## Testing

All V2.1 tests **structurally** stay; their assertions update to match the new schema:

- `test_chunker.py`: new tiny-library fixture with the new schema (one article per product, with `body_md` containing a few headings + paragraphs). Asserts chunk metadata correctness (product, category, title, chunk_index) and that the chunk text includes the breadcrumb prefix.
- `test_ingest.py`: counts adapted to the new fixture (~6 articles → ~12–18 chunks). Idempotency, per-product counts, ChromaDB artefacts, queryability.
- `test_retriever.py`: queries against the new fixture; product filter for each of the six products; confidence gate.
- `test_prompt.py`: asserts the **new** locked SYSTEM_PROMPT text verbatim; cite handle format for the new schema.
- `test_citations.py`: parses the new format `[Product · category · Title]`; validates against retrieved chunks; strips hallucinated cites.
- `test_llm.py`: `FakeProvider` stays. New `test_claude_code_provider.py` exists but only asserts the constructor raises when `claude` is not on PATH (we mock `shutil.which` to return `None`); we do NOT exercise a real CLI call in CI.
- `test_orchestrator.py`: stub LLM, retrieval-first pipeline kept from V2.1; assertions updated to new citation format.
- `test_integration.py`: 5-case golden Q&A re-curated against the new tiny library.
- `test_settings.py`: drop the keyring test; keep the JSON round-trip tests.

Target: ~40 chatbot tests green. Scraper's 50 tests untouched.

---

## Non-goals (still)

- No API key path. No keyring usage anywhere.
- No multi-source ingestion beyond `library/kb/`.
- No multi-user server.
- No fine-tuning.
- No agentic / multi-step reasoning yet.

---

## Risks + mitigations

- **`claude-agent-sdk` is new.** If its API surface changes, the provider may need an adjustment. Mitigation: pin to the version we test with in `requirements.txt`; the abstraction is one file (`claude_code_provider.py`) so swapping is cheap.
- **Bundle size.** Removing the `torch.cuda` exclusion will grow the exe somewhat (the cuda submodule is small but pulls in initialiser code). Target stays 300–700 MB.
- **Library size growth.** 1,466 articles × ~2 chunks each ≈ 3,000 chunks. Reindex on CPU: 5–10 minutes. Mitigation: progress dialog with chunk count + ETA; persist between runs.
- **Ambiguity false positives with 6 products.** Mitigation: keep the 60% dominant-product threshold; tune in the golden Q&A test set.
- **Citation format change breaks old chats.** Old saved sessions used the TFS-id form; they'll display as `[unverified]` if re-opened. Mitigation: don't migrate; old sessions stay readable but tagged.
