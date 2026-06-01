# Design: Contoso KB AI Chatbot — Beta
**Date:** 2026-05-28
**Status:** Approved design, pending implementation
**Consumes:** the local KB library produced by `ContosoKBScraper.exe` (V2.1)

---

## Goal

A local Windows desktop application — `ContosoKBChatbot.exe` — that lets internal team members ask natural-language questions and get accurate, cited answers grounded **strictly** in the scraped Contoso KB library (TradeDesk, Web4, SalesHub release notes). For a financial ERP context, accuracy is paramount: the assistant must abstain when it cannot find a source rather than guess, every claim it makes must cite a specific KB record, and it must ask clarifying questions when intent is ambiguous.

The chatbot ships as a single `.exe` alongside the scraper, with each teammate bringing their own Anthropic API key. No external knowledge sources, no Slack/email/Confluence-API integrations, no internet retrieval — the KB library on disk is the entire universe of allowed facts.

---

## Non-Goals (MVP / beta)

- No multi-source ingestion (no Slack, Jira, email, Confluence-live, web search).
- No OpenAI provider yet (Anthropic only at MVP; provider abstraction designed so OpenAI can be added without refactor).
- No local LLM (Ollama) at MVP — would be a later "air-gapped" mode.
- No multi-user server, no auth, no centralised history — each teammate runs their own .exe on their own machine.
- No fine-tuning. We rely on retrieval quality + a tight system prompt + post-hoc citation validation.
- No agentic / multi-step reasoning (single-pass RAG only). Re-evaluate after beta if specific question categories fail.
- No editing of source library from the chatbot — read-only.

---

## High-level Architecture

```
                    ┌──────────────────────────────────────────┐
   user question →  │ PySide6 GUI (chat window)                │
                    │   • QListView of messages                │
                    │   • product / version filters            │
                    │   • Reindex / Settings / Clear           │
                    │   • cost + token footer                  │
                    └──────────┬───────────────────────────────┘
                               │  (signals/slots)
                    ┌──────────▼───────────────────────────────┐
                    │ orchestrator.handle_turn(...)            │
                    │   step 1: ambiguity check  ─┐            │
                    │   step 2: retrieve + rerank │ no LLM if  │
                    │   step 3: confidence gate  ─┘ abstaining │
                    │   step 4: build prompt                   │
                    │   step 5: LLM call (Anthropic)           │
                    │   step 6: validate citations             │
                    │   step 7: persist usage row              │
                    └──┬───────┬───────┬────────────┬──────────┘
                       │       │       │            │
                  ┌────▼──┐ ┌──▼───┐ ┌─▼──────┐ ┌───▼────────┐
                  │retrie-│ │prompt│ │ LLM    │ │ usage log  │
                  │ver    │ │      │ │provider│ │ (jsonl)    │
                  └────┬──┘ └──────┘ └────────┘ └────────────┘
                       │
                  ┌────▼────────┐
                  │ ChromaDB    │ ← built from library/*.json by ingest.py
                  │ + reranker  │
                  └─────────────┘
```

Three things separate this from a "naive RAG":
1. **Ambiguity check is a separate, pre-LLM step.** If the question lacks product/version anchoring and retrieval is diffuse, we ask the user a clarifying question without spending an LLM call.
2. **Confidence gate at the retriever, not just in the prompt.** A bad retrieval makes the answer "I don't have this in the KB" deterministically — no LLM call, no chance for the model to invent.
3. **Citation validator after the LLM** — every `[cite:...]` tag the model emits is checked against the chunks actually retrieved. Hallucinated citations are stripped and replaced with an "(unverified)" tag with a logged warning.

---

## Folder Structure

```
Knowledge Base/
├── library/                            ← source-mode scraper output (may be empty)
├── dist/                               ← runtime distribution
│   ├── ContosoKBScraper.exe           ← existing
│   ├── ContosoKBChatbot.exe           ← NEW
│   ├── library/                        ← shared corpus (read by both exes)
│   └── state/                          ← scraper state (run.log etc.)
└── Dev/
    └── kb_chatbot/
        ├── __init__.py
        ├── gui.py                      ← PySide6 entry point (chat window)
        ├── config.py                   ← paths, default model, thresholds, freeze-aware
        ├── settings.py                 ← API key (keyring) + library path persistence
        ├── ingest.py                   ← library/ → chunks → embed → ChromaDB
        ├── chunker.py                  ← row + version chunk builders
        ├── retriever.py                ← query embedding, vector search, rerank, gate
        ├── prompt.py                   ← strict system prompt + context formatting
        ├── citations.py                ← cite parser + post-LLM validator
        ├── llm/
        │   ├── __init__.py
        │   ├── base.py                 ← abstract LLMProvider (sync + streaming)
        │   └── anthropic_provider.py   ← Haiku default, Sonnet selectable
        ├── chat/
        │   ├── __init__.py
        │   ├── session.py              ← per-session turn list, persistence
        │   └── orchestrator.py         ← per-turn pipeline (the 7 steps above)
        ├── state/                      ← runtime state when running from source
        │   ├── chroma/                 ← persistent vector DB
        │   ├── chats/<session-id>.json ← saved transcripts
        │   ├── run.log
        │   └── usage.jsonl             ← append-only per-query record
        └── tests/
            ├── fixtures/
            │   ├── tiny_library/       ← synthetic 3-version mini library
            │   └── golden_qa.json      ← curated Q&A regression set
            ├── test_chunker.py
            ├── test_retriever.py
            ├── test_citations.py
            ├── test_prompt.py
            ├── test_orchestrator.py
            └── test_settings.py
```

When packaged as exe, `BASE_DIR = Path(sys.executable).parent` (`dist/`) and `state/` lives next to the exe — same freeze-aware pattern used by the scraper. The library path is settable in the GUI (default: auto-discovered) so the chatbot can run against a relocated library or a development copy.

---

## Component Designs

### `config.py`
Holds defaults only:
- `BASE_DIR`, `STATE_DIR`, `LIBRARY_DEFAULT` (freeze-aware, identical pattern to scraper).
- `DEFAULT_MODEL = "claude-haiku-4-5-20251001"`, `AVAILABLE_MODELS = {...}`.
- `EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"`, `RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"`.
- `TOP_K_RETRIEVE = 30`, `TOP_K_RERANK = 8`.
- `CONFIDENCE_FLOOR = 0.30` (post-rerank score below this → abstain). Tunable in settings (advanced).
- `MAX_HISTORY_TURNS = 6` (rolling window of chat history sent to LLM).

### `settings.py`
- `Settings(api_key: Optional[str], library_path: Path, default_model: str, confidence_floor: float)`.
- Persisted JSON at `state/settings.json` (everything except API key).
- API key stored via `keyring.set_password("kb_chatbot", "anthropic", key)`; never written to JSON, never logged.
- Migration-safe load: missing keys fall back to defaults.

### `chunker.py`
Two builders.

**`build_row_chunks(version_data: dict) -> list[Chunk]`** — one Chunk per row across sections. Each Chunk has:
```python
@dataclass
class Chunk:
    id: str               # "<product>/<version>/<section>/<row_idx>"
    text: str             # row rendered as plain text for embedding
    metadata: dict        # {product, version, section, row_id (TFS), title, url, md_path, kind="row"}
```
The `text` is built by serialising the row dict to readable lines (e.g., `"TFS 14093 · Dashboard Activity · Bug fix in F10 key behavior … Risk: LOW"`). Headers and IDs are explicit because both are great search anchors.

**`build_version_chunks(version_data: dict) -> Chunk`** — one Chunk per version page, summarising its sections + counts. Used when the user asks "what's in version 3.0.1.9".

Both deterministic — re-running gives identical chunk IDs (essential for incremental updates later).

### `ingest.py`
- `ingest(library_path: Path, chroma_path: Path, on_progress=lambda...) -> IngestReport`.
- Walks `<library>/<product>/versions/*.json`, builds chunks, embeds in batches of 64, upserts to ChromaDB with metadata.
- Idempotent: existing IDs are upserted (new embedding overwrites; deletes for now are not handled — full reindex on demand).
- Returns `IngestReport(versions_seen, chunks_created, products: dict[str,int], duration_s)` for the GUI's reindex panel.

### `retriever.py`
```python
@dataclass
class RetrievalResult:
    chunks: list[Chunk]              # post-rerank, top K
    raw_top_score: float             # before rerank
    rerank_top_score: float          # after rerank
    abstain_reason: Optional[str]    # set if confidence_gate decided to abstain
```

`retrieve(query: str, *, product_filter: Optional[str], version_filter: Optional[tuple[str,str]]) -> RetrievalResult`:
1. Embed query with `sentence-transformers/all-MiniLM-L6-v2`.
2. ChromaDB query with metadata filter (`product`, `version` range when given). Pull `TOP_K_RETRIEVE` candidates.
3. Cross-encoder rerank (small local model) — score each (query, chunk.text) pair, sort.
4. Confidence gate: if no chunk's rerank score ≥ `CONFIDENCE_FLOOR`, return `abstain_reason="no_relevant_kb_match"` with empty chunks.
5. Otherwise return top `TOP_K_RERANK` chunks.

### `prompt.py`
- `build_system_prompt() -> str` — returns the strict KB-only contract. Locked text including the format rules.
- `format_context(chunks: list[Chunk]) -> str` — renders retrieved chunks into a numbered context block with citation handles like `[TradeDesk 3.0.1.9 · enhancement · TFS-14093]`.
- `format_history(history: list[Turn]) -> list[Message]` — rolls the last `MAX_HISTORY_TURNS` turns into Anthropic message format.
- `build_messages(...) -> list[Message]` — composes the final payload.

**The system prompt (final text, locked):**

> You are the Contoso Knowledge Base Assistant. You answer questions about the TradeDesk, Web4, and SalesHub release notes — and only the release notes.
>
> **Hard rules — no exceptions:**
> 1. You may only use facts from the CONTEXT block below. You have no other knowledge of Contoso products. Do not use general knowledge, intuition, or assumptions.
> 2. If the answer is not in the context, reply exactly: `I don't have a record of this in the knowledge base. Want to refine the question?` — and offer one specific refinement (different product, broader version range, related keyword). Never invent.
> 3. Every factual claim must end with a citation tag in this exact form: `[<Product> <Version> · <section> · <ID>]` — e.g. `[SalesHub 2.0.2.1 · enhancement · TFS-57196]`. A claim without a valid citation is forbidden.
> 4. If the user's intent is ambiguous (could refer to multiple products, a too-broad version range, or a vague feature name), do not answer. Instead, ask exactly one clarifying question.
> 5. Format the answer as: one-sentence direct answer first; then bullet list of relevant items (each with citation); then a "Searched:" footnote naming the product(s) and version range you considered.
>
> Do not editorialise. Do not apologise. Do not speculate about future versions. Do not summarise sections that weren't retrieved.

### `citations.py`
- `parse_citations(answer: str) -> list[Citation]` — regex parses tags in the locked form.
- `validate(answer: str, retrieved: list[Chunk]) -> ValidationResult`:
  - Each citation must match a retrieved chunk's `(product, version, section, row_id)` exactly.
  - Hallucinated citations: stripped from the displayed answer, replaced with `[unverified]`, logged at warning level.
  - Sentences that lose their citation become flagged in the GUI (small "(unverified)" badge) so the user knows.

### `llm/base.py` + `llm/anthropic_provider.py`
```python
class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], *, model: str, max_tokens: int = 1024) -> LLMResponse: ...

@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: int
    cost_estimate_usd: float
```
`AnthropicProvider` wraps the official `anthropic` SDK. Cost estimate uses a small dict of per-million-token prices kept in `config.py` (Haiku, Sonnet — values reviewable / updateable). On HTTP errors: caught, surfaced to GUI as a friendly message, full traceback in `run.log`.

### `chat/session.py`
- `Turn(role, content, citations, retrieved_ids, model, tokens_in, tokens_out, latency_ms, ts)`.
- `Session(id, turns)` — persisted to `state/chats/<id>.json` on each new turn.
- Provides `history_for_llm(max_turns)` → trimmed message list.

### `chat/orchestrator.py`
The 7-step pipeline (see flow at top). Pure function from `(user_msg, session, filters, settings)` → `Turn`. Easy to unit-test by injecting fake providers and a stub retriever.

```python
def handle_turn(user_msg: str, session: Session, filters: Filters, settings: Settings, deps: Deps) -> Turn:
    # 1. Pre-flight ambiguity check (cheap, no LLM).
    # The check uses three signals, evaluated in order:
    #   a) Did the user (or active filter, or recent chat history) name a product? If yes → not ambiguous.
    #   b) Pull a quick top-10 retrieval. If results span 2+ products AND no single product has
    #      ≥60% of the rerank weight, treat as ambiguous.
    #   c) Otherwise (single-product results OR strong dominant product), not ambiguous.
    # Clarifying-question text is templated, e.g.:
    #   "Multiple products have records that look related. Which one are you asking about — TradeDesk, Web4, or SalesHub?"
    if needs_clarification(user_msg, session, filters, deps.retriever):
        return Turn.clarification(_make_clarifying_question(user_msg, deps.retriever))

    # 2-3. Retrieve + gate
    result = deps.retriever.retrieve(user_msg, ...)
    if result.abstain_reason:
        return Turn.abstain(reason=result.abstain_reason)

    # 4-5. Build prompt and call LLM
    messages = build_messages(system_prompt, format_context(result.chunks), session.history_for_llm(), user_msg)
    response = deps.llm.chat(messages, model=settings.default_model)

    # 6. Validate citations
    validated = citations.validate(response.text, result.chunks)

    # 7. Record + return
    deps.usage_log.append(Turn(...))
    return Turn(...)
```

### `gui.py` (PySide6)
- `QMainWindow` with a top toolbar (`Reindex`, `Settings`, model selector, `Clear chat`), a filter row (product dropdown, optional version range), a central `QListView` of messages, an input box + `Send`, and a status footer (today's queries / tokens / cost).
- Each message is rendered via a custom `QStyledItemDelegate` using `markdown` → HTML. Citations are rendered as small badges; clicking opens the corresponding `.md` in the OS's default viewer. "Show retrieved sources (N)" expands inline to a panel of the actual chunks the model saw.
- A `Worker(QThread)` runs `orchestrator.handle_turn` so the UI stays responsive. Cancel is supported via a `CancellationToken` (reuses the scraper's pattern).
- On startup: load settings; if no API key set, show first-run dialog. If `state/chroma/` is missing or older than `library/` mtime, surface a non-blocking banner "Index out of date — Reindex now?"
- Errors anywhere in the pipeline produce a friendly message in the chat ("Sorry — the Anthropic API returned an error. Details in run.log."), never crash the app.

---

## Data Schema (per turn, written to `state/usage.jsonl`)

```json
{
  "ts": "2026-05-28T10:42:11",
  "session_id": "2026-05-28-103011-a7e9",
  "user_msg": "When did IBAN validation get added to SalesHub?",
  "filters": {"product": null, "version_min": null, "version_max": null},
  "ambiguity_check": "passed",
  "retrieval": {"raw_top_score": 0.61, "rerank_top_score": 0.78, "retrieved_ids": ["saleshub/2.0.2.1/enhancement/0"]},
  "gate": "passed",
  "model": "claude-haiku-4-5-20251001",
  "tokens_in": 1247,
  "tokens_out": 198,
  "cost_estimate_usd": 0.00041,
  "latency_ms": 1183,
  "citations": [{"raw": "SalesHub 2.0.2.1 · enhancement · TFS-57196", "verified": true}],
  "status": "ok"
}
```

This file is the audit trail for accuracy investigation. Greppable, append-only, never truncated.

---

## Strict Accuracy Contract — User-Visible Behaviour

| Situation | Behaviour |
|---|---|
| Question is clear, retrieval has high-confidence match | Answer with citations |
| Question is ambiguous (multi-product / vague feature name) | Ask one clarifying question; no LLM call yet |
| Question is clear but retrieval has nothing above confidence floor | "I don't have a record of this in the knowledge base. Want to refine the question?" — no LLM call |
| LLM emits a hallucinated citation | Citation stripped, "(unverified)" badge, warning logged |
| LLM throws an API error | Friendly chat message, full traceback in `run.log`, conversation continues |
| KB version was scraped today but query is about something only in a later version | Honest abstain (we only know what's in the library) |

---

## Logging & Cost

- `state/run.log` — structured (`%(asctime)s %(levelname)s %(name)s %(message)s`). DEBUG-level detail for retrieval and prompt construction; INFO for orchestrator decisions; WARNING for citation issues; ERROR for exceptions. Rotates daily, 30-day retention.
- `state/usage.jsonl` — one line per turn as above. **Never rotated**, so audit history is permanent.
- GUI status footer shows session and today's totals. Settings → "View logs" opens the folder in Explorer.

---

## Reindex Strategy

- "Reindex" button in toolbar — disables UI, runs `ingest.ingest()` with progress callback (chunks done / total) feeding a small dialog.
- Time estimate: ~1–2 minutes for 156 versions on CPU (≈1000–2000 row chunks at all-MiniLM-L6-v2 batch-64).
- Cold start (no Chroma index): app prompts user to reindex once before first message.
- Library-changed detection: on startup compare `<library>/INDEX.md` mtime to `state/chroma/index_meta.json` mtime — if library is newer, soft-banner the user.

---

## Testing

- **Unit tests** (`pytest`, no network): chunker shape, retriever filtering + gate logic (with a fake embedding model), citation parser + validator, prompt builder (asserts the locked system prompt text, asserts citations match retrieved IDs only).
- **Tiny-library fixture**: 3 synthetic versions across 3 products at `tests/fixtures/tiny_library/` used by ingest + orchestrator tests so the suite runs in seconds without touching the real library.
- **Golden Q&A set** (`tests/fixtures/golden_qa.json`): 10–15 curated questions with expected `(retrieved_ids, must_cite_ids, must_abstain)` triples. The integration test runs each through `orchestrator.handle_turn` with a stub LLM that echoes a deterministic answer; the test asserts retrieval correctness + citation contract, NOT the LLM's wording. This is the accuracy regression suite.
- **Manual smoke test**: run real Anthropic Haiku against the same Q&A set; record actual answers for review; not part of CI.

---

## Dependencies

New runtime:
- `sentence-transformers>=2.7` (CPU; pulls in `torch` — large but unavoidable for local embeddings)
- `chromadb>=0.5`
- `anthropic>=0.34`
- `keyring>=24`
- `markdown>=3.6`

Already installed: `PySide6`, `pytest`.

Bundle size (rough): scraper exe ~284 MB. Chatbot exe estimate ~300–500 MB depending on whether we trim torch's CUDA assets (we don't need them — embeddings run CPU-only on small models). The implementation plan will include the PyInstaller spec tweaks to trim torch correctly and aim for ~300 MB.

---

## Implementation Phases (preview — the plan will detail steps)

1. Scaffold (`Dev/kb_chatbot/`, requirements, freeze-aware config) + `settings.py` + tests.
2. `chunker.py` + `ingest.py` + ChromaDB persistence + ingest tests using tiny-library fixture.
3. `retriever.py` (embedding query, ChromaDB filtering, reranker, confidence gate) + tests.
4. `prompt.py` + `citations.py` + tests (locked system prompt asserted verbatim).
5. `llm/base.py` + `llm/anthropic_provider.py` + a fake provider for tests.
6. `chat/session.py` + `chat/orchestrator.py` + golden Q&A integration tests.
7. `gui.py` — chat window with worker thread, citations panel, filters, settings.
8. PyInstaller spec for the chatbot exe; size verification; smoke test of the bundled exe.

---

## Open Decisions / Future Work (not blocking MVP)

- **OpenAI provider:** the `LLMProvider` abstraction makes this a single new file once we ship.
- **Air-gapped mode (Ollama):** add `OllamaProvider`. Quality trade-off; revisit if a teammate needs no-cloud.
- **Verified external sources:** post-MVP. Same architecture, just additional ingest pipelines feeding into Chroma with a `source_type` metadata field.
- **Per-row updates instead of full reindex:** stable Chunk IDs already support this; add an incremental ingest later.
- **Shared usage analytics:** if needed, a tiny aggregator script that combines each teammate's `usage.jsonl`.
