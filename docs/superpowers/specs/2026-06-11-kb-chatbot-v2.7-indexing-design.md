# KB Chatbot v2.7 — Indexing Overhaul, Codex Fix & Version Surfacing — Design Spec

**Date:** 2026-06-11
**Status:** Approved (design); pending spec review → implementation plan
**Supersedes nothing.** Builds on v2.6 (one-folder offline build, PII-redacted tickets).

---

## 1. Context & Problem

User report: "startup is still slow; Codex failed to run at all; re-indexing took too long with no real-time progress or logs; not sure ticket data was included." Investigation (evidence from `dist/ContosoKBChatbot/chatbot_state/run.log`, `settings.json`, and source layout) found five concrete issues:

1. **Codex never ran.** `codex exec` rejected the prompt: *"Failed to read prompt from stdin: input is not valid UTF-8 (invalid byte at offset 95)."* `codex_provider._run_codex_exec` uses `subprocess.run(cmd, input=prompt, text=True)`. `text=True` encodes stdin with the Windows locale codepage (cp1252), but KB/ticket prompts contain non-cp1252 characters (em-dash, smart quotes, `✦`). Codex requires UTF-8.

2. **Tickets were not indexed.** The exe's persisted `library_path` was `…\Knowledge Base\library` (missing the `\kb` leaf). `ingest()` derives the ticket folder as `library_path.parent / "tickets"` → `…\Knowledge Base\tickets`, which does not exist (tickets live at `…\library\tickets`). Result: last reindex embedded **1471 articles / 4075 chunks and zero tickets**, with no warning. The ticket path is silently derived from the KB path — fragile.

3. **Re-index is slow.** Because `library_path` pointed at `…\library`, ingest also scanned all **23,431 ticket files as candidate "articles"** (read + parsed, then skipped) with no progress shown. The reported run was **490.5s** for a *partial* index. It is a full rebuild every time with no incremental skip; a correct full index (KB + ~14.5k ticket chunks) would be far slower.

4. **No real-time progress / logs.** `on_progress(done, total)` fires only during the embed loop. Source scanning + PII-redaction of 23k tickets happens before the bar moves, and there are no per-stage or per-source messages.

5. **Heavy startup.** The log shows the embedding model loaded 3× per session and a `chromadb … table collections already exists` error on startup (likely aggravated by the index living under a OneDrive-synced folder).

## 2. Goals

- Codex answers queries again (UTF-8 stdin).
- Tickets are reliably discovered, indexed, and searchable; the flow reports exactly what it indexed.
- Re-indexing is incremental (near-instant when nothing changed) with an explicit force-rebuild.
- A dedicated indexing panel shows real-time progress, per-stage logs, and per-source counts.
- Startup is faster (lazy reranker, shared embedder, resilient chroma open).
- Version is surfaced in the window title and the exe filename, from a single source of truth.

## 3. Non-Goals

- The v3 BETA retrieval overhaul (hybrid BM25+vector / bge reranker) — stays off `master`.
- The scraper (`scraper/`) — untouched.
- PII-redaction *logic* — unchanged. Only *when/whether* it runs (incremental skip) changes.

## 4. Locked Decisions

| Decision | Choice |
|---|---|
| Run model | Dev indexes on this machine (all 23,431 tickets); ship the **prebuilt** chroma index in the exe folder. End users query only; **no raw tickets ship**. |
| Reindex behavior | **Incremental** (path+mtime+size diff) with a **Force full rebuild** option. |
| Progress UI | **Dedicated indexing panel** (progress bar + live log + per-source counters). |
| Version | **v2.7**. `APP_VERSION` constant in `config.py`; title `Contoso KB Chatbot v2.7`; exe `ContosoKBChatbot-v2.7.exe`. |

## 5. Detailed Design

### A. Codex UTF-8 fix — `Dev/kb_chatbot/llm/codex_provider.py`
- `_run_codex_exec`: `subprocess.run(cmd, input=prompt, capture_output=True, encoding="utf-8", errors="replace", timeout=CODEX_TIMEOUT_S)`. Replacing `text=True` with explicit `encoding="utf-8"` forces UTF-8 on both stdin encode and stdout decode.
- `codex_login_ok`: same `encoding="utf-8"` on its `subprocess.run`.
- Regression test: a prompt containing `—`, `✦`, and a smart quote encodes to UTF-8 bytes without error (assert the encode path, mocking the subprocess).

### B. Robust source discovery — `Dev/kb_chatbot/ingest.py`
- New helper `resolve_sources(library_path, tickets_path=None) -> (kb_root, tickets_root)`:
  - If `library_path` basename is `kb` → `kb_root = library_path`, `tickets_root = library_path.parent / "tickets"`.
  - Else if `library_path / "kb"` exists → `kb_root = library_path / "kb"`, `tickets_root = library_path / "tickets"`.
  - Else → `kb_root = library_path`, `tickets_root = library_path.parent / "tickets"` (current behavior, last resort).
  - An explicit `tickets_path` always wins.
- Both resolved roots and their file counts are emitted as events (§D) and returned in the report. A `0 tickets found` is surfaced prominently.

### C. Incremental indexing — `Dev/kb_chatbot/ingest.py`
- **Manifest** `index_manifest.json` in `chroma_path`. Keys are namespaced by source kind and the file's path relative to its own resolved root, so KB and ticket files never collide and keys are stable across runs: `kb/<relpath-from-kb_root>` (e.g. `kb/api/functions/createbank.json`) and `ticket/<filename>` (e.g. `ticket/ticket_40000.json`).
  ```json
  {
    "version": 1,
    "embed_model": "sentence-transformers/all-MiniLM-L6-v2",
    "files": {
      "kb/api/functions/createbank.json": {"mtime": 1718049600.0, "size": 2048, "chunk_ids": ["...", "..."]},
      "ticket/ticket_40000.json": {"mtime": 1718049601.0, "size": 1024, "chunk_ids": ["ticket_ab12cd34ef..."]}
    }
  }
  ```
- Algorithm:
  1. Scan KB + ticket files → `{relpath: (mtime, size)}`.
  2. Diff vs manifest → **added / changed (mtime or size differs) / removed / unchanged**. If `embed_model` changed, treat all as changed.
  3. `collection.delete(ids=…)` for chunk-ids of removed + changed files.
  4. For added + changed: read → build chunks (KB `build_article_chunks`, tickets `build_ticket_chunks` w/ redaction) → embed in `BATCH_SIZE` batches → `upsert`. Record each file's produced chunk-ids.
  5. Rewrite manifest (drop removed, update changed/added, keep unchanged).
  6. `force_rebuild=True`: `collection` cleared + manifest reset; all files treated as added.
- Signature: `ingest(library_path, chroma_path, *, tickets_path=None, on_event=None, force_rebuild=False, embedder=None, should_cancel=lambda: False) -> IngestReport`.
- `IngestReport` gains: `tickets_seen`, `chunks_deleted`, `unchanged_files`, `resolved_kb_path`, `resolved_tickets_path` (kept: `articles_seen`, `chunks_created`, `products`, `skipped`, `duration_s`).

### D. Event protocol + indexing panel — `ingest.py` + `gui.py`
- **Event** dict: `{"stage": str, "message": str, "current": int|None, "total": int|None, "counts": {...}}`. Stages in order: `scan`, `diff`, `parse_kb`, `redact_tickets`, `embed`, `persist`, `done` (and `error`). `counts` carries running totals (`kb_articles`, `tickets`, `chunks`, `removed`, `unchanged`, `skipped`).
- `IngestWorker(QThread)` re-emits each event via a `event = Signal(dict)` (replacing the bare `progress = Signal(int,int)`); keeps `finished`/`failed`.
- **`IndexingDialog(QDialog)`** (new): title bar, `QProgressBar`, a counters row (labels updated from `counts`), a read-only `QPlainTextEdit` log (timestamped lines from `message`), a **Force full rebuild** checkbox (only enabled before start), and Start/Cancel/Close buttons. Cancel sets a flag checked between batches (`should_cancel`). On `done`, shows the summary line and enables Close.
- The toolbar **Reindex** action opens this dialog instead of running silently.

### E. Startup speed — `Dev/kb_chatbot/retriever.py` + `gui.py`
- **Lazy reranker:** the cross-encoder loads on first `retrieve()` that needs reranking, not in `Retriever.__init__`. `InitWorker` then only loads the embedder + opens chroma → chat unlocks sooner. (Reranker still loads inside the turn worker thread, off the UI thread.)
- **Shared embedder:** `Retriever` exposes its `SentenceTransformer`; the GUI passes it into `ingest(..., embedder=…)` so reindex reuses one model instead of loading a second/third.
- **Resilient chroma open:** wrap `PersistentClient` creation; on the known `table collections already exists` InternalError, log a clear message and retry once. Log a WARNING if `chroma_path` is under a OneDrive-synced directory (path contains `OneDrive`), since cloud-sync of the live sqlite is the probable trigger.

### F. Version surfacing — `config.py`, `gui.py`, `ContosoKBChatbot.spec`, `build_chatbot_exe.bat`
- `config.APP_VERSION = "2.7"` — single source of truth.
- `gui.py`: `MainWindow.setWindowTitle(f"Contoso KB Chatbot v{config.APP_VERSION}")`; `app.setApplicationName(...)` likewise. Module docstrings → V2.7.
- `.spec`: read the version from `config.py` (parse the `APP_VERSION = "x.y"` line without importing heavy deps) and set `EXE(name=f"ContosoKBChatbot-v{VERSION}")` and `COLLECT(name=f"ContosoKBChatbot-v{VERSION}")`.
- `build_chatbot_exe.bat`: update the artifact path message to the versioned folder.

### G. Ship-prebuilt-index workflow
1. Dev runs the app from source (`scraper\venv\Scripts\python.exe Dev/kb_chatbot/gui.py`) with the default/ correct library path → opens the indexing panel → full build (KB + 23k tickets). Index lands in source `Dev/kb_chatbot/state/chroma`.
2. Build the onedir exe (`build_chatbot_exe.bat`).
3. Copy the prebuilt `chroma/` (+ `index_manifest.json`) into `dist/ContosoKBChatbot-v2.7/chatbot_state/chroma`. (Documented as an explicit post-build step; the implementation plan will decide whether the build bat performs the copy automatically.)
4. Frozen `BASE_DIR = Path(sys.executable).parent` (onedir exe folder) already resolves `chatbot_state/chroma` correctly — no path change needed for the query-only end-user path.

## 6. Testing

- `test_codex_provider`: UTF-8 prompt encodes without error; `encoding="utf-8"` passed to subprocess.
- `test_ingest` (extend): `resolve_sources` for the three layouts; incremental diff (added/changed/removed/unchanged); removed file's chunks deleted; manifest round-trips; `embed_model` change forces full re-embed; `force_rebuild` clears.
- Ticket inclusion: an ingest over a tiny fixture library + tickets reports `tickets_seen > 0` and the ticket chunk is retrievable.

## 7. Verification before build (standing rule: sandbox before compile)

1. Full reindex from source; confirm the panel reports a non-zero **tickets** count (~14.5k chunks total) and resolved ticket path.
2. Smoke query whose answer should cite a ticket → returns a ticket citation (search uses ticket data).
3. Codex query returns a real answer (UTF-8 fix verified live).
4. Only then build the versioned exe; copy the prebuilt index; launch the exe and confirm title shows `v2.7` and a query works.

## 8. Risks

- chroma `collection.delete` + `upsert` churn on incremental updates — mitigated by batching and a force-rebuild escape hatch.
- Manifest/chroma drift if chroma is edited out-of-band — force-rebuild resolves; `embed_model` guard catches model changes.
- OneDrive sync of the live index — warned in logs; the ship model keeps the end-user index stable (read-mostly).
