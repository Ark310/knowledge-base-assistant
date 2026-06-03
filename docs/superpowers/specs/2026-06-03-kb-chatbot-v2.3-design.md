# KB Chatbot v2.3 — Design Spec

**Date:** 2026-06-03  
**Status:** Approved  
**Scope:** Six enhancements to the existing v2.2 chatbot — multi-turn conversation, clickable source links, instant startup, file/screenshot uploads, Learn Mode, and article suggestions on low confidence.

---

## Context

The v2.2 chatbot is a PySide6 desktop app backed by ChromaDB vector search, SentenceTransformer embeddings, CrossEncoder reranking, and Claude (Haiku/Sonnet) via the Claude SDK. It has 1,466 KB articles across six products ingested into ~3,000 chunks.

The retrieval core (ChromaDB, chunker, ingest pipeline) is **unchanged** in this release. All six features are additive or corrective changes layered on top of the existing architecture.

---

## 1. Multi-Turn Conversation

### Problem

`ClaudeCodeProvider.chat()` calls `_latest_user_text(messages)` which strips the full conversation history down to only the newest user message before sending to the Claude SDK client. The session history is correctly built in `session.py` and threaded through `orchestrator.py` → `prompt.py` → `build_messages()` — but discarded at the last step. Every turn is effectively single-shot.

### Solution

**Part 1 — Pass full history to Claude.**  
`_query_persistent()` in `llm/claude_code_provider.py` changes its signature from `prompt: str` to `messages: list[dict]`. The full alternating user/assistant list produced by `build_messages()` is passed directly to the Claude SDK client, which supports multi-turn natively.

**Part 2 — Topic-drift detection.**  
In `chat/orchestrator.py`, after retrieval, compare the current turn's top rerank score against the previous turn's score (stored on the `Session`). If the current score drops below 0.20 while the previous was above 0.50, the orchestrator marks the turn as a topic shift. Claude receives an additional context note: `"[TOPIC SHIFT: treat this as a fresh question, do not reference prior context]"`. This prevents Claude from hallucinating continuity between unrelated topics.

### Behaviour Change

- Follow-up questions ("how do I reverse that?", "what about for Web2?") resolve correctly — Claude has the prior answer in context and understands referential phrases
- Genuine topic changes cause the bot to re-anchor cleanly without blending unrelated contexts
- History window remains at 6 turns (12 raw) as before — no token budget change

### Files

| File | Change |
|------|--------|
| `llm/claude_code_provider.py` | `_query_persistent()` accepts `messages: list[dict]`; remove `_latest_user_text()` call |
| `chat/orchestrator.py` | Topic-drift check after rerank; inject drift note into context block when triggered; store last score on `Session` |
| `chat/session.py` | Add `last_rerank_score: float` field to `Session`; update on each completed turn |

---

## 2. Clickable Source Links

### Problem

The article URL is stored in every retrieved chunk's metadata (`url` field). The citation validator in `citations.py` parses `[Product · Category · Title]` and validates against retrieved chunks, but never surfaces the URL. The chat widget renders plain text, so even if URLs were present they would not be clickable.

### Solution

**Part 1 — Enrich citations with URL.**  
`citations.py` adds a `url: str` field to `CitationMatch`. When a citation is validated against a retrieved chunk, the chunk's `url` metadata is copied onto the match object.

**Part 2 — Update context block and system prompt.**  
`prompt.py` updates the context block header format from:
```
1. [TradeDesk · Dealing · Book a Retail Deal]
```
to:
```
1. [TradeDesk · Dealing · Book a Retail Deal](https://help.contoso.example/display/...)
```

The system prompt rule changes from:
> Every claim MUST end with `[Product · Category · Title]`.

to:
> Every claim MUST end with `[Title](url)` using the exact URL from the CONTEXT block. Never invent a URL.

Claude can only use URLs that appear in the context block — hallucinated links are structurally impossible.

**Part 3 — Markdown rendering in chat widget.**  
`gui.py` switches the chat display from a plain `QTextEdit` to a `QTextBrowser` (already in PySide6, no new dependency) with `setOpenExternalLinks(True)`. Markdown link syntax `[Title](url)` renders as a real hyperlink that opens in the default browser. Existing `[unverified]` tags remain visible — they appear as plain text since they have no URL to link.

### Files

| File | Change |
|------|--------|
| `citations.py` | Add `url: str` to `CitationMatch`; populate from matched chunk metadata |
| `prompt.py` | Update context block header format; update system prompt citation rule |
| `gui.py` | Replace chat `QTextEdit` with `QTextBrowser`; enable external links |

---

## 3. Instant Startup

### Problem

The Qt window is not created until after `_warm_up_llm()` completes. Warm-up boots the Claude SDK client (2–5s) and implicitly triggers SentenceTransformer + CrossEncoder model loading (1–3s) — all on the main thread. The OS window never appears until this finishes, causing a ~4-minute perceived startup on cold machines.

### Solution

**`InitWorker` QThread.** The main thread performs exactly two actions at launch: build the UI and show the window (both instant). An `InitWorker(QThread)` is started immediately after and runs concurrently:

```
Main thread:    build UI → show window → wait for InitWorker.ready signal
InitWorker:     load SentenceTransformer → load CrossEncoder → warm up Claude SDK → emit ready
```

**UI states:**

| State | Input box | Send button | Status bar |
|-------|-----------|-------------|------------|
| Initialising | Disabled (grey) | Disabled | `⟳ Initialising — please wait...` |
| Ready | Enabled | Enabled | `Ready` |
| First-ever run | Disabled | Disabled | `⟳ Downloading models (first run)...` |

All other UI elements (KB tab, settings, toolbar) are fully interactive during init.

**Model reuse.** `InitWorker` instantiates `Retriever` once and stores it on the main window object. The per-query `Retriever()` instantiation in the send handler is removed — the shared instance is reused for all queries, eliminating per-query model reload time.

**Indexing policy.** Reindex is never triggered at startup. The "Reindex" button tooltip reads: `"Run after adding new articles to the knowledge base"`.

**Target:** Window visible < 1 second. Input unlocked < 15 seconds on warm machine (models on disk). First-ever run shows `"Downloading models..."` once only.

### Files

| File | Change |
|------|--------|
| `gui.py` | Add `InitWorker(QThread)`; restructure `__init__` to show window before init; add status bar states; store shared `Retriever` on `self`; remove per-query `Retriever()` instantiation |

---

## 4. File & Screenshot Uploads

### Supported Types

| Type | Extensions | How processed |
|------|------------|---------------|
| Images | `.png` `.jpg` `.jpeg` `.gif` `.webp` | Base64-encoded, sent as Claude vision content block |
| Text files | `.md` `.txt` `.json` `.log` | Extracted as plain text, prepended to user message as fenced code block |

Multiple attachments per message are supported.

### UI — Attachment Bar

A collapsible bar between the chat history and input row. Hidden when empty, visible when files are attached:

```
┌─────────────────────────────────────────────────────┐
│  📎 error_screenshot.png  ×    deal_log.txt  ×      │  ← attachment bar
├─────────────────────────────────────────────────────┤
│  Type your question here...            [📎] [Send]  │  ← input row
└─────────────────────────────────────────────────────┘
```

Each attachment renders as a chip with filename and `×` to remove. Bar disappears after Send clears attachments.

### Three Ways to Attach

1. **Drag and drop** — drag files onto the chat window anywhere; `dragEnterEvent` / `dropEvent` handlers accept valid extensions
2. **Paste** (`Ctrl+V`) — if clipboard contains an image (e.g. Snipping Tool screenshot), it attaches automatically
3. **Paperclip button** — opens `QFileDialog` filtered to supported extensions

### Message Construction

Images are passed as multimodal content blocks in the user turn:
```python
{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "<base64>"}}
```

Text files are prepended as a fenced block:
```
[Attached: deal_log.txt]
```
... file contents (truncated to 20,000 chars if larger) ...
```

User question: Why is this deal failing?
```

**System prompt addition:**  
> If the user attaches an image or file, use it as additional context alongside the KB articles. Do not describe the image unless asked.

### Limits

| Limit | Value | Behaviour on exceed |
|-------|-------|---------------------|
| Image size | 4 MB | Warning chip, file rejected |
| Text file length | 20,000 characters | Truncated with `[truncated]` notice in block |
| Attachments per message | 5 | Paperclip button disabled after 5 |

### Files

| File | Change |
|------|--------|
| `gui.py` | Drag-drop handlers, clipboard paste, attachment bar widget, paperclip button, modified send handler to package attachments |
| `prompt.py` | `build_messages()` accepts optional `attachments: list[Attachment]`; builds multimodal content blocks for images; prepends text file blocks to user message |
| `chat/session.py` | `Turn` gains `attachments: list[str]` (filenames only) for usage logging — no file content stored in session |

---

## 5. Learn Mode

### Access Control

A `Learn Mode` button in the toolbar opens a password dialog. The plaintext password `YOUR_LEARN_PASSWORD_HERE` is **never stored** — on first launch it is hashed with SHA-256 and written to `settings.json` as `learn_mode_hash`. Comparison is always hash-vs-hash.

Failed attempts are logged to `state/usage.jsonl` with `kind: "learn_mode_failed_auth"`. An `Exit Learn Mode` button replaces the toolbar button while active — no password needed to exit.

### In-Session UI

Normal chat works identically in Learn Mode. Two controls appear below every bot response:

```
┌──────────────────────────────────────────────────────────────┐
│  Bot answer displayed here...                                │
│                                                              │
│  [✓ Mark as Correct]   [✎ Correct / Add to KB]             │
└──────────────────────────────────────────────────────────────┘
```

**"Mark as Correct"** — saves the Q&A pair as a verified learned entry (green chip confirmation).

**"Correct / Add to KB"** — opens an inline editor below the response:
- Text area pre-populated with the bot's answer (editable)
- Product dropdown (`TradeDesk`, `API`, `Web2`, `Web4`, `SalesHub`, `Other`)
- Topic label text field (free text, e.g. "Dealing", "Finance", "Getting Started")
- Optional Confluence URL field
- `Save to KB` button — commits entry; `Cancel` — closes editor without saving

### Storage — `library/learned/`

Each entry is a `.json` file using the same schema as scraped articles:

```json
{
  "space_key": "learned",
  "space_name": "Learned",
  "product": "tradedesk",
  "title": "How to reverse a posted deal",
  "url": "https://help.contoso.example/display/...",
  "body_md": "To reverse a posted deal: 1. Navigate to...",
  "learned_at": "2026-06-03T14:22:00",
  "contributed_by": "learn_mode",
  "original_question": "How do I undo a deal that was already posted?"
}
```

The ingest pipeline requires **zero changes** — learned entries are picked up automatically on the next Reindex.

### Retrieval & Citation Behaviour

Learned chunks carry `product: "learned"` and `space_key: "learned"` in ChromaDB metadata. Citations render as `[Learned · Topic · Title](url)` — visually distinct from official KB articles so users know the answer came from internal feedback rather than official Contoso documentation.

### Files

| File | Change |
|------|--------|
| `settings.py` | Add `learn_mode_hash: str` field; add `check_learn_password(candidate: str) -> bool` method; write default hash on first launch |
| `gui.py` | Learn Mode toolbar button; password dialog; exit button; per-response feedback controls; inline correction editor |
| `chat/learn_writer.py` | **New file.** `write_learned_entry(...)` — creates `library/learned/` if absent; writes `.json` entry with stable filename `learned_<sha1>.json` |

---

## 6. Article Suggestions on Abstain / Low Confidence

### Triggers

| Condition | Top rerank score | Current behaviour | New behaviour |
|-----------|-----------------|-------------------|---------------|
| Abstain | < 0.30 | "Not in my KB" generic message | "Not in my KB" + suggestion list |
| Low confidence | 0.30 – 0.45 | Answers (may be unreliable) | Answers + `---` + suggestion footnote |

### Suggestion Engine

On either trigger, a second retrieval pass runs at threshold 0.10, `top_k=5`, no reranking. The top 3 results deduplicated by title are formatted as a clickable list. This pass is lightweight — it reuses the already-loaded `Retriever` and does not call Claude.

**Abstain response format:**
```
I don't have enough information in the knowledge base to answer this confidently.

Here are some articles that might be related — do any of these match what you're looking for?

• [Book a Retail Deal](https://help.contoso.example/display/...)  — TradeDesk · Dealing
• [Deal Types Overview](https://help.contoso.example/display/...)  — TradeDesk · Dealing
• [Settlement Workflow](https://help.contoso.example/display/...)  — TradeDesk · Finance

If none of these help, try rephrasing your question or use Learn Mode to add the missing information.
```

**Low-confidence footnote (appended to normal answer):**
```
---
*Not fully certain this covers your question. You might also check:*
• [Related Article](url) — Product · Category
```

### Clarification Before Suggestions

If the query is fewer than 4 words **and** contains no product name, the orchestrator asks one clarifying question before running the suggestion pass:
> "Are you asking about TradeDesk, the API, Web2, Web4, or SalesHub?"

This avoids noisy suggestions for underspecified one-word queries.

### Files

| File | Change |
|------|--------|
| `chat/orchestrator.py` | Call `SuggestionEngine` on abstain and low-confidence paths; short-query clarification check |
| `retriever.py` | Add `suggest(query, top_k=5, threshold=0.10) -> list[ChunkResult]` — separate from main `retrieve()` path |
| `prompt.py` | `format_suggestions(chunks) -> str` — formats suggestion list as Markdown bullet links |

---

## Summary of All File Changes

| File | Sections | Nature of change |
|------|----------|-----------------|
| `llm/claude_code_provider.py` | 1 | Pass full `messages` list to SDK; remove `_latest_user_text()` |
| `chat/orchestrator.py` | 1, 6 | Topic-drift check; suggestion engine calls; clarification check |
| `chat/session.py` | 1, 4 | Add `last_rerank_score`; add `attachments` to `Turn` |
| `chat/learn_writer.py` | 5 | **New file** — write learned entries to `library/learned/` |
| `citations.py` | 2 | Add `url` to `CitationMatch` |
| `prompt.py` | 2, 4, 6 | Context block format; citation rule; multimodal builder; suggestion formatter |
| `retriever.py` | 6 | Add `suggest()` method |
| `settings.py` | 5 | Add `learn_mode_hash`; add `check_learn_password()` |
| `gui.py` | 2, 3, 4, 5 | `QTextBrowser`; `InitWorker`; attachment bar; Learn Mode UI |

**Unchanged:** `chunker.py`, `ingest.py`, `config.py`, all scraper code, all existing tests (retrieval core untouched)

---

## Out of Scope

- Graphify integration — designed for code AST graphs, not applicable to help-desk markdown documentation
- Automated accounting/finance knowledge import from public sources — replaced by Learn Mode as the mechanism for knowledge bridging
- Scheduling / auto-reindex — remains manual only

---

## Testing Notes

Existing ~40 tests cover the retrieval core and remain valid. New tests needed:

- `test_multi_turn.py` — verify full history reaches Claude SDK; verify topic-drift injection
- `test_citations_url.py` — verify `CitationMatch.url` populated from chunk metadata
- `test_init_worker.py` — verify window appears before `InitWorker` completes
- `test_attachments.py` — verify base64 image blocks; text file truncation; size limits
- `test_learn_mode.py` — verify password hash check; verify `.json` written to `library/learned/`; verify ingest picks it up
- `test_suggestions.py` — verify suggestion pass fires on abstain; verify short-query clarification path
