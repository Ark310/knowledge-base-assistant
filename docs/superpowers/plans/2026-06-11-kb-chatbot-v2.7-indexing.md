# KB Chatbot v2.7 — Indexing Overhaul, Codex Fix & Version Surfacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make re-indexing incremental and observable (live progress + per-stage logs), guarantee ticket data is discovered/indexed/searchable, fix Codex (UTF-8 stdin), speed up startup, and surface v2.7 in the window title and exe filename.

**Architecture:** `ingest.py` becomes incremental — a JSON manifest tracks each source file by mtime+size and the chunk-ids it produced, so a reindex only re-embeds changed files and deletes chunks for removed ones. Source roots (KB + sibling `tickets/`) are resolved robustly. `ingest()` emits structured progress events consumed by a new modal `IndexingDialog`. The live `Retriever` and `ingest()` share one chroma client (passed `collection=`) and one embedder, fixing the double-open `table collections already exists` error; the reranker loads lazily to speed startup. Version lives in one `APP_VERSION` constant read by the GUI and the `.spec`.

**Tech Stack:** Python 3, PySide6 (Qt), chromadb (PersistentClient), sentence-transformers (SentenceTransformer + CrossEncoder), pytest, PyInstaller (onedir).

**Test runner (this repo):** `scraper\venv\Scripts\python.exe -m pytest <path> -v` run from the repo root `C:\Users\AbdulRaqeebKhatri\OneDrive\Documents\Knowledge Base`.

**Branching/commits:** Work on a dedicated branch so the in-progress v2.6 working-tree changes are not entangled. Each task commits **only its own files** via explicit `git add <paths>`. Commit messages end with the required `Co-Authored-By` trailer.

---

## File Structure

- `Dev/kb_chatbot/config.py` — **modify**: add `APP_VERSION = "2.7"`; bump docstring.
- `Dev/kb_chatbot/llm/codex_provider.py` — **modify**: UTF-8 stdin/stdout on both `subprocess.run` calls.
- `Dev/kb_chatbot/ingest.py` — **rewrite**: `resolve_sources`, `open_persistent_client`, manifest helpers, incremental `ingest()` with events, extended `IngestReport`, `IngestCancelled`.
- `Dev/kb_chatbot/retriever.py` — **modify**: shared `embedder` param, lazy reranker, resilient client open.
- `Dev/kb_chatbot/gui.py` — **modify**: versioned title; `IngestWorker` emits events; new `IndexingDialog`; `_reindex` opens it and reuses the retriever's collection+embedder; bump docstring.
- `ContosoKBChatbot.spec` — **modify**: read `APP_VERSION`, version the EXE + COLLECT name.
- `build_chatbot_exe.bat` — **modify**: versioned artifact path message.
- `Dev/kb_chatbot/tests/test_codex_provider.py` — **modify**: UTF-8 encoding tests.
- `Dev/kb_chatbot/tests/test_ingest.py` — **modify**: incremental/resolve/manifest/ticket tests; update 2 existing assertions.
- `Dev/kb_chatbot/tests/test_retriever_lazy.py` — **create**: lazy reranker + shared embedder.
- `Dev/kb_chatbot/tests/test_version.py` — **create**: APP_VERSION present.

---

## Task 0: Branch

- [ ] **Step 1: Create and switch to the feature branch**

```bash
git checkout -b feat/kb-chatbot-v2.7
```

Expected: `Switched to a new branch 'feat/kb-chatbot-v2.7'`. (Pre-existing modified files come along untouched; we never `git add` them.)

---

## Task 1: Codex UTF-8 stdin fix

**Files:**
- Modify: `Dev/kb_chatbot/llm/codex_provider.py`
- Test: `Dev/kb_chatbot/tests/test_codex_provider.py`

- [ ] **Step 1: Write failing tests**

Append to `Dev/kb_chatbot/tests/test_codex_provider.py`:

```python
def test_run_codex_exec_uses_utf8_encoding(monkeypatch):
    """The prompt must be sent as UTF-8, not the Windows locale codepage."""
    import json as _json
    captured = {}

    class _Proc:
        stdout = _json.dumps({"type": "turn.completed",
                              "usage": {"input_tokens": 1, "output_tokens": 1}})
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("ok")
        return _Proc()

    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", fake_run)

    cp._run_codex_exec("em—dash ✦ smart’quote prompt", "gpt-5.4-mini")
    assert captured.get("encoding") == "utf-8"
    assert captured.get("errors") == "replace"
    assert "text" not in captured  # must not rely on text=True (locale codepage)


def test_codex_login_ok_uses_utf8(monkeypatch):
    captured = {}

    class _Proc:
        returncode = 0

    monkeypatch.setattr(cp, "_login_ok_cache", False)
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run",
                        lambda cmd, **kw: (captured.update(kw), _Proc())[1])
    cp.codex_login_ok()
    assert captured.get("encoding") == "utf-8"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_codex_provider.py::test_run_codex_exec_uses_utf8_encoding Dev/kb_chatbot/tests/test_codex_provider.py::test_codex_login_ok_uses_utf8 -v`
Expected: FAIL (current code passes `text=True`, so `encoding`/`errors` absent).

- [ ] **Step 3: Implement — `_run_codex_exec` subprocess call**

In `Dev/kb_chatbot/llm/codex_provider.py`, change the `subprocess.run` in `_run_codex_exec` from:

```python
        proc = subprocess.run(cmd, input=prompt, capture_output=True,
                              text=True, timeout=CODEX_TIMEOUT_S)
```

to:

```python
        proc = subprocess.run(cmd, input=prompt, capture_output=True,
                              encoding="utf-8", errors="replace",
                              timeout=CODEX_TIMEOUT_S)
```

- [ ] **Step 4: Implement — `codex_login_ok` subprocess call**

In `codex_login_ok`, change:

```python
        r = subprocess.run(_codex_argv(["login", "status"]),
                           capture_output=True, text=True, timeout=10)
```

to:

```python
        r = subprocess.run(_codex_argv(["login", "status"]),
                           capture_output=True, encoding="utf-8",
                           errors="replace", timeout=10)
```

- [ ] **Step 5: Run the full codex test file**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_codex_provider.py -v`
Expected: PASS (all existing + 2 new).

- [ ] **Step 6: Commit**

```bash
git add Dev/kb_chatbot/llm/codex_provider.py Dev/kb_chatbot/tests/test_codex_provider.py
git commit -m "fix(v2.7): send codex prompt as UTF-8 (was locale cp1252, broke on em-dash/smart-quote)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Version constant + window title + spec/bat

**Files:**
- Modify: `Dev/kb_chatbot/config.py`
- Modify: `Dev/kb_chatbot/gui.py:366` (window title) and `:1092` (`setApplicationName`)
- Modify: `ContosoKBChatbot.spec`
- Modify: `build_chatbot_exe.bat`
- Test: `Dev/kb_chatbot/tests/test_version.py`

- [ ] **Step 1: Write failing test**

Create `Dev/kb_chatbot/tests/test_version.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config


def test_app_version_is_2_7():
    assert config.APP_VERSION == "2.7"
```

- [ ] **Step 2: Run to verify it fails**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_version.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'APP_VERSION'`.

- [ ] **Step 3: Add `APP_VERSION` to config.py**

In `Dev/kb_chatbot/config.py`, change the first line docstring and add the constant right after the imports block. Replace:

```python
"""V2.6 static defaults + freeze-aware paths + provider registry + tickets. No persisted settings live here."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import sys
```

with:

```python
"""V2.7 static defaults + freeze-aware paths + provider registry + tickets. No persisted settings live here."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import sys

# Single source of truth for the app version. Surfaced in the window title and
# the exe filename (read by ContosoKBChatbot.spec). Bump here only.
APP_VERSION = "2.7"
```

- [ ] **Step 4: Run to verify it passes**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_version.py -v`
Expected: PASS.

- [ ] **Step 5: Use the version in the window title**

In `Dev/kb_chatbot/gui.py`, change line ~366 from:

```python
        self.setWindowTitle("Contoso KB Chatbot")
```

to:

```python
        self.setWindowTitle(f"Contoso KB Chatbot v{config.APP_VERSION}")
```

And change `main()`'s `app.setApplicationName("Contoso KB Chatbot")` (line ~1092) to:

```python
    app.setApplicationName(f"Contoso KB Chatbot v{config.APP_VERSION}")
```

Also bump the module docstring (line 1) from `"""V2.6 KB Chatbot GUI. ...` to `"""V2.7 KB Chatbot GUI. ...` (keep the rest of the sentence).

- [ ] **Step 6: Version the exe in the .spec**

In `ContosoKBChatbot.spec`, insert after the `from PyInstaller.utils.hooks import collect_all` line:

```python
import re as _re
_cfg_src = open("Dev/kb_chatbot/config.py", encoding="utf-8").read()
_vm = _re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _cfg_src)
VERSION = _vm.group(1) if _vm else "0.0"
```

Change `EXE(... name="ContosoKBChatbot", ...)` to `name=f"ContosoKBChatbot-v{VERSION}"`, and `COLLECT(... name="ContosoKBChatbot")` to `name=f"ContosoKBChatbot-v{VERSION}"`.

- [ ] **Step 7: Update the build bat artifact message**

In `build_chatbot_exe.bat`, change the final echo line to:

```bat
echo Build complete. Artifact: dist\ContosoKBChatbot-v2.7\ContosoKBChatbot-v2.7.exe  (distribute the whole ContosoKBChatbot-v2.7 folder).
```

- [ ] **Step 8: Sanity-check the GUI module imports**

Run: `scraper\venv\Scripts\python.exe -c "import Dev.kb_chatbot.gui"`
Expected: no traceback (prints nothing).

- [ ] **Step 9: Commit**

```bash
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/gui.py ContosoKBChatbot.spec build_chatbot_exe.bat Dev/kb_chatbot/tests/test_version.py
git commit -m "feat(v2.7): APP_VERSION constant; show v2.7 in window title + exe filename

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Ingest foundation — report, source resolution, resilient client, manifest

This task adds the pure helpers and the extended report **without** changing `ingest()`'s body yet (that's Task 4). It is safe because Task 4 replaces the whole file; here we still write the helpers + tests so they are verified in isolation. To keep the repo runnable between tasks, we write the **complete new `ingest.py`** in Task 4 — so in **this** task we only add tests for the helpers and confirm they fail, then Task 4 makes them pass. (Combined here for a single coherent rewrite.)

> Implementation note: Tasks 3 and 4 both target `ingest.py`. Implement the helper tests (Step 1 below) first, then proceed straight into Task 4's full-file rewrite, then run **both** task's tests together at Task 4 Step 4.

**Files:**
- Test: `Dev/kb_chatbot/tests/test_ingest.py`

- [ ] **Step 1: Add helper + incremental tests (will fail until Task 4)**

Append to `Dev/kb_chatbot/tests/test_ingest.py`:

```python
import json
from Dev.kb_chatbot.ingest import resolve_sources, IngestReport


def _write_article(dirpath, name, title, body="hello world"):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / name).write_text(
        json.dumps({"product": "api", "title": title, "body_md": body}),
        encoding="utf-8")


def test_resolve_sources_kb_leaf(tmp_path):
    (tmp_path / "kb").mkdir()
    (tmp_path / "tickets").mkdir()
    kb, tk = resolve_sources(tmp_path / "kb")
    assert kb == tmp_path / "kb"
    assert tk == tmp_path / "tickets"


def test_resolve_sources_library_parent(tmp_path):
    (tmp_path / "kb").mkdir()
    (tmp_path / "tickets").mkdir()
    kb, tk = resolve_sources(tmp_path)
    assert kb == tmp_path / "kb"
    assert tk == tmp_path / "tickets"


def test_resolve_sources_explicit_tickets_wins(tmp_path):
    kb, tk = resolve_sources(tmp_path / "kb", tickets_path=tmp_path / "custom")
    assert tk == tmp_path / "custom"


def test_incremental_skips_unchanged(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    assert r1.articles_seen == 1 and r1.chunks_embedded >= 1
    r2 = ingest(lib, chroma)
    assert r2.chunks_embedded == 0
    assert r2.unchanged_files == 1
    assert r2.total_chunks == r1.total_chunks


def test_incremental_processes_added_file(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    _write_article(lib / "api", "b.json", "B", body="more content here")
    r3 = ingest(lib, chroma)
    assert r3.articles_seen == 1
    assert r3.chunks_embedded >= 1
    assert r3.total_chunks == r1.total_chunks + r3.chunks_embedded


def test_incremental_deletes_removed_file_chunks(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    _write_article(lib / "api", "b.json", "B", body="second article body")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    (lib / "api" / "b.json").unlink()
    r2 = ingest(lib, chroma)
    assert r2.chunks_deleted >= 1
    assert r2.total_chunks < r1.total_chunks


def test_force_rebuild_reembeds_everything(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    r2 = ingest(lib, chroma, force_rebuild=True)
    assert r2.chunks_embedded == r1.chunks_embedded
    assert r2.total_chunks == r1.total_chunks


def test_embed_model_change_forces_rebuild(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    mf = chroma / "index_manifest.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    data["embed_model"] = "some-other-model"
    mf.write_text(json.dumps(data), encoding="utf-8")
    r2 = ingest(lib, chroma)
    assert r2.chunks_embedded == r1.chunks_embedded


def test_tickets_indexed_via_explicit_path(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    tickets = tmp_path / "tickets"
    tickets.mkdir()
    (tickets / "ticket_40000.json").write_text(json.dumps({
        "ticket_id": "40000",
        "title": "Login fails",
        "product": "tradedesk",
        "resolution_url": "https://support.example/40000",
        "comments": [
            {"type": "note", "body": "Customer cannot log in."},
            {"type": "comment", "author": "Staff",
             "body": "Cleared the cache and restarted the service; resolved."},
        ],
    }), encoding="utf-8")
    chroma = tmp_path / "chroma"
    report = ingest(lib, chroma, tickets_path=tickets)
    assert report.tickets_seen == 1
    assert report.resolved_tickets_path == str(tickets)
    import chromadb
    client = chromadb.PersistentClient(path=str(chroma))
    coll = client.get_collection("kbs")
    kinds = {m.get("kind") for m in coll.get()["metadatas"]}
    assert "ticket" in kinds
    client.close()


def test_event_stages_emitted(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    stages = []
    ingest(lib, chroma, on_event=lambda e: stages.append(e["stage"]))
    for s in ("scan", "diff", "embed", "persist", "done"):
        assert s in stages
```

- [ ] **Step 2: Update the two existing assertions that change meaning**

In `Dev/kb_chatbot/tests/test_ingest.py`, replace `test_ingest_creates_chunks` and `test_ingest_idempotent` with:

```python
def test_ingest_creates_chunks():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert report.chunks_embedded >= 6
        assert report.total_chunks >= 6


def test_ingest_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        r1 = ingest(FIX, Path(tmp))
        r2 = ingest(FIX, Path(tmp))
        assert r1.total_chunks == r2.total_chunks
        assert r2.chunks_embedded == 0
        assert r2.unchanged_files == 6
```

(Leave `test_ingest_reports_article_count`, `test_ingest_per_product_counts`, and `test_ingest_collection_queryable_after_ingest` unchanged.)

- [ ] **Step 3: Run to confirm they fail (no incremental ingest yet)**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ingest.py -v`
Expected: FAIL/ERROR — `resolve_sources`/`IngestReport.total_chunks`/`force_rebuild` don't exist yet. Proceed to Task 4.

---

## Task 4: Incremental `ingest()` rewrite with events

**Files:**
- Rewrite: `Dev/kb_chatbot/ingest.py`
- Test: `Dev/kb_chatbot/tests/test_ingest.py` (from Task 3)

- [ ] **Step 1: Replace the entire contents of `Dev/kb_chatbot/ingest.py`**

```python
"""V2.7 ingest: incremental indexing of KB articles + support tickets into ChromaDB.

Every source file is tracked in index_manifest.json (path -> mtime, size, and the
chunk-ids it produced) so a reindex only re-embeds added/changed files and deletes
chunks for removed ones. Resolves the KB root and its sibling tickets/ folder
robustly so tickets are never silently missed, and emits structured progress
events for the GUI indexing panel."""
from __future__ import annotations
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import chromadb
from sentence_transformers import SentenceTransformer

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import build_article_chunks, Chunk
from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks

log = logging.getLogger("kb_chatbot.ingest")

COLLECTION_NAME = "kbs"
BATCH_SIZE = 64
DELETE_BATCH = 256
MANIFEST_NAME = "index_manifest.json"

OnEvent = Callable[[dict], None]


class IngestCancelled(Exception):
    """Raised inside ingest() when should_cancel() returns True."""


@dataclass
class IngestReport:
    articles_seen: int = 0          # KB articles added/changed this run
    tickets_seen: int = 0           # tickets producing a chunk this run
    chunks_embedded: int = 0        # chunks newly embedded this run
    chunks_deleted: int = 0         # chunks removed this run (changed + removed files)
    total_chunks: int = 0           # total chunks in the collection after this run
    unchanged_files: int = 0        # source files skipped because mtime+size matched
    skipped: int = 0                # unreadable / no body_md / ticket with no resolution
    products: dict[str, int] = field(default_factory=dict)
    resolved_kb_path: str = ""
    resolved_tickets_path: str = ""
    duration_s: float = 0.0


def resolve_sources(library_path, tickets_path=None) -> tuple[Path, Path]:
    """Resolve (kb_root, tickets_root) regardless of whether library_path points
    at .../library or .../library/kb. An explicit tickets_path always wins."""
    library_path = Path(library_path)
    if library_path.name == "kb":
        kb_root = library_path
        tickets_root = library_path.parent / "tickets"
    elif (library_path / "kb").is_dir():
        kb_root = library_path / "kb"
        tickets_root = library_path / "tickets"
    else:
        kb_root = library_path
        tickets_root = library_path.parent / "tickets"
    if tickets_path is not None:
        tickets_root = Path(tickets_path)
    return kb_root, tickets_root


def open_persistent_client(chroma_path):
    """Open a chroma PersistentClient, retrying once on failure (the
    'table collections already exists' InternalError shows up when the sqlite is
    mid-sync under OneDrive or a prior client didn't close cleanly)."""
    chroma_path = Path(chroma_path)
    if "onedrive" in str(chroma_path).lower():
        log.warning("Chroma index lives under a OneDrive-synced path (%s); "
                    "cloud-sync of the live sqlite can corrupt it. A non-synced "
                    "location is recommended.", chroma_path)
    try:
        return chromadb.PersistentClient(path=str(chroma_path))
    except Exception as exc:
        log.warning("Chroma open failed (%s); retrying once", exc)
        import gc
        gc.collect()
        time.sleep(0.5)
        return chromadb.PersistentClient(path=str(chroma_path))


def _gather_article_jsons(kb_root: Path) -> list[Path]:
    if not kb_root.exists():
        return []
    out: list[Path] = []
    for child in sorted(kb_root.iterdir()):
        if child.is_dir():
            out.extend(sorted(child.rglob("*.json")))
    return [p for p in out if p.name != "index.json"]


def _gather_ticket_jsons(tickets_root: Path) -> list[Path]:
    if not tickets_root.exists():
        return []
    return [p for p in sorted(tickets_root.glob("ticket_*.json")) if p.name != "index.json"]


def _load_manifest(chroma_path: Path) -> dict:
    mf = chroma_path / MANIFEST_NAME
    if mf.exists():
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("files"), dict):
                return data
        except Exception:
            log.warning("Manifest unreadable; rebuilding from empty")
    return {"version": 1, "embed_model": "", "files": {}}


def _save_manifest(chroma_path: Path, manifest: dict) -> None:
    (chroma_path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")


def _sig(p: Path) -> list:
    st = p.stat()
    return [st.st_mtime, st.st_size]


def _embed_batch(model, texts: list[str]) -> list[list[float]]:
    vecs = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def ingest(
    library_path,
    chroma_path,
    *,
    tickets_path=None,
    on_event: Optional[OnEvent] = None,
    force_rebuild: bool = False,
    embedder=None,
    collection=None,
    should_cancel: Callable[[], bool] = lambda: False,
) -> IngestReport:
    """Incrementally index KB articles + tickets into ChromaDB.

    Pass `collection=` to reuse an already-open chroma collection (the GUI passes
    the live Retriever's collection so only one client touches the sqlite). Pass
    `embedder=` to reuse a loaded SentenceTransformer. `on_event` receives dicts
    {stage, message, current, total, counts}."""
    started = time.time()
    emit = on_event or (lambda e: None)
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    kb_root, tickets_root = resolve_sources(library_path, tickets_path)
    report = IngestReport(resolved_kb_path=str(kb_root),
                          resolved_tickets_path=str(tickets_root))

    own_client = collection is None
    client = None
    if own_client:
        client = open_persistent_client(chroma_path)
        collection = client.get_or_create_collection(name=COLLECTION_NAME)

    model = embedder if embedder is not None else SentenceTransformer(config.EMBED_MODEL)

    manifest = _load_manifest(chroma_path)
    model_changed = manifest.get("embed_model") not in ("", config.EMBED_MODEL)
    if force_rebuild or model_changed:
        ids = collection.get(include=[]).get("ids", [])
        for i in range(0, len(ids), DELETE_BATCH):
            collection.delete(ids=ids[i:i + DELETE_BATCH])
        manifest = {"version": 1, "embed_model": config.EMBED_MODEL, "files": {}}
    manifest["embed_model"] = config.EMBED_MODEL
    files = manifest["files"]

    # ── Scan ──────────────────────────────────────────────────────────────────
    emit({"stage": "scan", "message": "Scanning sources…",
          "current": None, "total": None, "counts": {}})
    kb_files = _gather_article_jsons(kb_root)
    ticket_files = _gather_ticket_jsons(tickets_root)
    emit({"stage": "scan",
          "message": f"KB root {kb_root}: {len(kb_files)} files · "
                     f"Tickets {tickets_root}: {len(ticket_files)} files",
          "current": None, "total": None,
          "counts": {"kb_files": len(kb_files), "ticket_files": len(ticket_files)}})
    if not ticket_files:
        emit({"stage": "scan",
              "message": f"WARNING: 0 ticket files found at {tickets_root}",
              "current": None, "total": None, "counts": {}})

    current: dict[str, tuple] = {}
    for f in kb_files:
        current["kb/" + f.relative_to(kb_root).as_posix()] = ("kb", f, _sig(f))
    for tf in ticket_files:
        current["ticket/" + tf.name] = ("ticket", tf, _sig(tf))

    # ── Diff ──────────────────────────────────────────────────────────────────
    added, changed, removed, unchanged = [], [], [], []
    for key, (_kind, _path, sig) in current.items():
        prev = files.get(key)
        if prev is None:
            added.append(key)
        elif [prev.get("mtime"), prev.get("size")] != sig:
            changed.append(key)
        else:
            unchanged.append(key)
    for key in list(files):
        if key not in current:
            removed.append(key)
    report.unchanged_files = len(unchanged)
    emit({"stage": "diff",
          "message": f"{len(added)} new · {len(changed)} changed · "
                     f"{len(removed)} removed · {len(unchanged)} unchanged",
          "current": None, "total": None,
          "counts": {"new": len(added), "changed": len(changed),
                     "removed": len(removed), "unchanged": len(unchanged)}})

    # ── Delete chunks for removed + changed files ───────────────────────────────
    delete_ids: list[str] = []
    for key in removed + changed:
        delete_ids.extend(files.get(key, {}).get("chunk_ids", []))
    for i in range(0, len(delete_ids), DELETE_BATCH):
        collection.delete(ids=delete_ids[i:i + DELETE_BATCH])
    report.chunks_deleted = len(delete_ids)
    for key in removed:
        files.pop(key, None)

    # ── Build chunks for added + changed files ──────────────────────────────────
    to_process = added + changed
    kb_keys = [k for k in to_process if current[k][0] == "kb"]
    ticket_keys = [k for k in to_process if current[k][0] == "ticket"]
    pending: list[Chunk] = []
    file_chunk_ids: dict[str, list[str]] = {}

    total_kb = len(kb_keys)
    for i, key in enumerate(kb_keys, 1):
        if should_cancel():
            raise IngestCancelled()
        _kind, f, _sigv = current[key]
        file_chunk_ids[key] = []
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Skipping unreadable %s: %s", f, exc)
            report.skipped += 1
            continue
        if not isinstance(data, dict) or not data.get("body_md"):
            report.skipped += 1
            continue
        product = data.get("product", "unknown")
        report.articles_seen += 1
        report.products[product] = report.products.get(product, 0) + 1
        chunks = build_article_chunks(data, f, kb_root)
        file_chunk_ids[key] = [c.id for c in chunks]
        pending.extend(chunks)
        if i % 50 == 0 or i == total_kb:
            emit({"stage": "parse_kb", "message": f"Parsed {i}/{total_kb} KB articles",
                  "current": i, "total": total_kb,
                  "counts": {"kb_articles": report.articles_seen, "chunks": len(pending)}})

    total_tk = len(ticket_keys)
    for i, key in enumerate(ticket_keys, 1):
        if should_cancel():
            raise IngestCancelled()
        _kind, tf, _sigv = current[key]
        file_chunk_ids[key] = []
        try:
            tdata = json.loads(tf.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Skipping unreadable ticket %s: %s", tf, exc)
            report.skipped += 1
            continue
        tchunks = build_ticket_chunks(tdata, tf)
        if tchunks:
            report.tickets_seen += 1
            file_chunk_ids[key] = [c.id for c in tchunks]
            pending.extend(tchunks)
        else:
            report.skipped += 1
        if i % 200 == 0 or i == total_tk:
            emit({"stage": "redact_tickets",
                  "message": f"Redacted + parsed {i}/{total_tk} tickets",
                  "current": i, "total": total_tk,
                  "counts": {"tickets": report.tickets_seen, "chunks": len(pending)}})

    # ── Embed + upsert ──────────────────────────────────────────────────────────
    total = len(pending)
    embedded = 0
    for i in range(0, total, BATCH_SIZE):
        if should_cancel():
            raise IngestCancelled()
        batch = pending[i:i + BATCH_SIZE]
        embeds = _embed_batch(model, [c.text for c in batch])
        collection.upsert(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            embeddings=embeds,
            metadatas=[c.metadata for c in batch],
        )
        embedded += len(batch)
        emit({"stage": "embed", "message": f"Embedded {embedded}/{total} chunks",
              "current": embedded, "total": total,
              "counts": {"chunks_embedded": embedded}})
    report.chunks_embedded = embedded

    # ── Persist manifest ────────────────────────────────────────────────────────
    for key in to_process:
        _kind, _path, sig = current[key]
        files[key] = {"mtime": sig[0], "size": sig[1],
                      "chunk_ids": file_chunk_ids.get(key, [])}
    manifest["files"] = files
    emit({"stage": "persist", "message": "Saving index manifest…",
          "current": None, "total": None, "counts": {}})
    _save_manifest(chroma_path, manifest)

    report.total_chunks = collection.count()
    report.duration_s = time.time() - started
    emit({"stage": "done",
          "message": (f"Done: +{report.chunks_embedded} embedded, "
                      f"-{report.chunks_deleted} removed, "
                      f"{report.total_chunks} total, {report.duration_s:.1f}s"),
          "current": total or 1, "total": total or 1,
          "counts": {"total_chunks": report.total_chunks,
                     "tickets": report.tickets_seen,
                     "kb_articles": report.articles_seen}})
    log.info("Ingest: +%d embedded, -%d removed, %d total, %.1fs (kb=%s tickets=%s)",
             report.chunks_embedded, report.chunks_deleted, report.total_chunks,
             report.duration_s, kb_root, tickets_root)
    if own_client and client is not None:
        client.close()
    return report
```

- [ ] **Step 2: Verify the legacy positional signature still parses**

Run: `scraper\venv\Scripts\python.exe -c "from Dev.kb_chatbot.ingest import ingest, resolve_sources, open_persistent_client, IngestReport, IngestCancelled, COLLECTION_NAME; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Run the full ingest test file (Task 3 + existing)**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ingest.py -v`
Expected: PASS (all — `resolve_sources` cases, incremental skip/add/delete, force-rebuild, embed-model-change, ticket inclusion, event stages, and the unchanged `articles_seen`/`per_product`/`queryable` tests).

- [ ] **Step 4: Commit**

```bash
git add Dev/kb_chatbot/ingest.py Dev/kb_chatbot/tests/test_ingest.py
git commit -m "feat(v2.7): incremental ingest (mtime+size manifest), robust ticket discovery, progress events, shared client/embedder

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Retriever — shared embedder, lazy reranker, resilient open

**Files:**
- Modify: `Dev/kb_chatbot/retriever.py`
- Test: `Dev/kb_chatbot/tests/test_retriever_lazy.py`

- [ ] **Step 1: Write failing tests**

Create `Dev/kb_chatbot/tests/test_retriever_lazy.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import numpy as np
import Dev.kb_chatbot.retriever as r


class _FakeST:
    def __init__(self, *a, **k):
        pass
    def encode(self, text, **k):
        return np.zeros(384)


def test_reranker_is_lazy(monkeypatch, tmp_path):
    calls = {"n": 0}

    class _FakeCE:
        def __init__(self, *a, **k):
            calls["n"] += 1
        def predict(self, pairs):
            return [0.0] * len(pairs)

    monkeypatch.setattr(r, "SentenceTransformer", _FakeST)
    monkeypatch.setattr(r, "CrossEncoder", _FakeCE)
    rt = r.Retriever(tmp_path / "chroma")
    assert rt._reranker is None        # not loaded at construction
    assert calls["n"] == 0
    rt._get_reranker()
    assert calls["n"] == 1             # loaded on first use
    rt._get_reranker()
    assert calls["n"] == 1             # cached afterwards


def test_retriever_uses_provided_embedder(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "CrossEncoder", lambda *a, **k: None)
    sentinel = _FakeST()
    rt = r.Retriever(tmp_path / "chroma", embedder=sentinel)
    assert rt.embedder is sentinel
```

- [ ] **Step 2: Run to verify failure**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_retriever_lazy.py -v`
Expected: FAIL — `Retriever.__init__` has no `embedder` kwarg and eagerly builds `self.reranker`; no `_reranker`/`_get_reranker`.

- [ ] **Step 3: Edit `Retriever.__init__` and the import**

In `Dev/kb_chatbot/retriever.py`, change the import line:

```python
from Dev.kb_chatbot.ingest import COLLECTION_NAME
```

to:

```python
from Dev.kb_chatbot.ingest import COLLECTION_NAME, open_persistent_client
```

Replace the `__init__` body (lines ~43-57) with:

```python
    def __init__(
        self,
        chroma_path: Path,
        *,
        top_k_retrieve: int = config.TOP_K_RETRIEVE,
        top_k_rerank: int = config.TOP_K_RERANK,
        confidence_floor: float = config.CONFIDENCE_FLOOR,
        embedder: Optional[SentenceTransformer] = None,
    ):
        self.client = open_persistent_client(chroma_path)
        self.collection = self.client.get_or_create_collection(name=COLLECTION_NAME)
        self.embedder = embedder if embedder is not None else SentenceTransformer(config.EMBED_MODEL)
        self._reranker: Optional[CrossEncoder] = None  # loaded lazily on first rerank
        self.top_k_retrieve = top_k_retrieve
        self.top_k_rerank = top_k_rerank
        self.confidence_floor = confidence_floor

    def _get_reranker(self) -> CrossEncoder:
        if self._reranker is None:
            log.info("Loading reranker model (first use)…")
            self._reranker = CrossEncoder(config.RERANKER_MODEL)
        return self._reranker
```

- [ ] **Step 4: Use the lazy reranker in `retrieve()`**

In `retrieve()`, change:

```python
        scores = self.reranker.predict(pairs)
```

to:

```python
        scores = self._get_reranker().predict(pairs)
```

- [ ] **Step 5: Run the retriever tests + existing retriever tests**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_retriever_lazy.py Dev/kb_chatbot/tests/test_retriever.py Dev/kb_chatbot/tests/test_retriever_floor.py -v`
Expected: PASS. (If `test_retriever.py` references `.reranker` directly, update those references to `_get_reranker()`; it uses `retrieve()` so it should pass unchanged.)

- [ ] **Step 6: Commit**

```bash
git add Dev/kb_chatbot/retriever.py Dev/kb_chatbot/tests/test_retriever_lazy.py
git commit -m "perf(v2.7): lazy reranker load + shared embedder + resilient chroma open

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: GUI — event-driven IngestWorker + IndexingDialog + reuse retriever client

**Files:**
- Modify: `Dev/kb_chatbot/gui.py`

> GUI glue follows the project's existing convention of no Qt unit tests; verified by the import check here and the manual run in Task 7.

- [ ] **Step 1: Add `QCheckBox` to the Qt imports**

In `Dev/kb_chatbot/gui.py`, in the `from PySide6.QtWidgets import (...)` block, add `QCheckBox` to the list (e.g. after `QPlainTextEdit, QInputDialog,`).

- [ ] **Step 2: Import the cancel exception**

Change:

```python
from Dev.kb_chatbot.ingest import ingest
```

to:

```python
from Dev.kb_chatbot.ingest import ingest, IngestCancelled
```

- [ ] **Step 3: Replace `IngestWorker` with an event-driven worker**

Replace the entire `class IngestWorker(QThread): ...` block (lines ~133-151) with:

```python
class IngestWorker(QThread):
    event = Signal(dict)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, library_path, chroma_path, *,
                 force_rebuild=False, embedder=None, collection=None):
        super().__init__()
        self.library_path = library_path
        self.chroma_path = chroma_path
        self.force_rebuild = force_rebuild
        self.embedder = embedder
        self.collection = collection
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            report = ingest(
                self.library_path, self.chroma_path,
                on_event=lambda e: self.event.emit(e),
                force_rebuild=self.force_rebuild,
                embedder=self.embedder,
                collection=self.collection,
                should_cancel=lambda: self._cancel,
            )
            self.finished.emit(report)
        except IngestCancelled:
            self.failed.emit("Cancelled.")
        except Exception as exc:
            log.exception("Ingest failed")
            self.failed.emit(str(exc))
```

- [ ] **Step 4: Add the `IndexingDialog` class**

Insert this class definition just before `class MainWindow(QMainWindow):` (around line ~363):

```python
class IndexingDialog(QDialog):
    """Modal reindex panel: live progress bar, per-source counters, stage log."""

    def __init__(self, parent, library_path, chroma_path, embedder, collection):
        super().__init__(parent)
        self.setWindowTitle("Reindex Knowledge Base")
        self.resize(720, 480)
        self._library_path = library_path
        self._chroma_path = chroma_path
        self._embedder = embedder
        self._collection = collection
        self._worker: Optional[IngestWorker] = None
        self.report = None

        layout = QVBoxLayout(self)
        self._force_cb = QCheckBox("Force full rebuild (re-embed everything)")
        layout.addWidget(self._force_cb)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self._counts = QLabel("Idle. Press Start to index.")
        self._counts.setStyleSheet("color:#555;")
        layout.addWidget(self._counts)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_view, stretch=1)

        row = QHBoxLayout()
        self._start_btn = QPushButton("Start")
        self._cancel_btn = QPushButton("Cancel"); self._cancel_btn.setEnabled(False)
        self._close_btn = QPushButton("Close")
        row.addWidget(self._start_btn); row.addWidget(self._cancel_btn)
        row.addStretch(); row.addWidget(self._close_btn)
        layout.addLayout(row)

        self._start_btn.clicked.connect(self._start)
        self._cancel_btn.clicked.connect(self._do_cancel)
        self._close_btn.clicked.connect(self.reject)

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"{ts}  {msg}")

    def _start(self):
        self._start_btn.setEnabled(False)
        self._force_cb.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._close_btn.setEnabled(False)
        self.progress.setValue(0)
        self._log("Starting reindex…")
        self._worker = IngestWorker(
            self._library_path, self._chroma_path,
            force_rebuild=self._force_cb.isChecked(),
            embedder=self._embedder, collection=self._collection)
        self._worker.event.connect(self._on_event)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    @Slot(dict)
    def _on_event(self, e: dict):
        msg = e.get("message")
        if msg:
            self._log(msg)
        cur, tot = e.get("current"), e.get("total")
        if tot:
            self.progress.setValue(int(cur * 100 / tot))
        counts = e.get("counts") or {}
        if counts:
            self._counts.setText(" · ".join(f"{k}: {v}" for k, v in counts.items()))

    @Slot(object)
    def _on_finished(self, report):
        self.report = report
        self.progress.setValue(100)
        self._log(f"KB root:    {report.resolved_kb_path}")
        self._log(f"Tickets:    {report.resolved_tickets_path}")
        self._log(f"DONE in {report.duration_s:.1f}s — +{report.chunks_embedded} embedded, "
                  f"-{report.chunks_deleted} removed, {report.total_chunks} total · "
                  f"{report.articles_seen} articles, {report.tickets_seen} tickets changed, "
                  f"{report.unchanged_files} unchanged")
        self._cancel_btn.setEnabled(False)
        self._close_btn.setEnabled(True)

    @Slot(str)
    def _on_failed(self, err: str):
        self._log(f"FAILED: {err}")
        self._start_btn.setEnabled(True)
        self._force_cb.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._close_btn.setEnabled(True)

    def _do_cancel(self):
        if self._worker:
            self._worker.cancel()
            self._log("Cancelling after the current batch…")
```

- [ ] **Step 5: Rewrite `_reindex` and delete the now-unused old ingest handlers**

Replace `_reindex` (lines ~1010-1020) with:

```python
    def _reindex(self):
        collection = self._retriever.collection if self._retriever else None
        embedder = self._retriever.embedder if self._retriever else None
        dlg = IndexingDialog(self, self.settings.library_path, config.CHROMA_DIR,
                             embedder, collection)
        dlg.exec()
        if dlg.report is not None:
            self._append("system",
                f"Reindex: +{dlg.report.chunks_embedded} embedded, "
                f"{dlg.report.total_chunks} total ({dlg.report.articles_seen} articles, "
                f"{dlg.report.tickets_seen} tickets) in {dlg.report.duration_s:.1f}s",
                "#1b5e20", "SYSTEM:")
```

Delete the three now-orphaned slots `_on_ingest_progress`, `_on_ingest_done`, and `_on_ingest_failed` (lines ~1022-1041) — the dialog owns this now. Also remove the `self.ingest_worker` references: in `__init__` delete `self.ingest_worker: Optional[IngestWorker] = None`, and in `_set_inputs_enabled`/`closeEvent` replace any `self.ingest_worker` checks with `False` (the modal dialog blocks the main window while indexing, so the main window has no concurrent ingest worker). Specifically, in `closeEvent` change `if self.worker or self.ingest_worker:` to `if self.worker:`.

- [ ] **Step 6: Import-check the GUI module**

Run: `scraper\venv\Scripts\python.exe -c "import Dev.kb_chatbot.gui; print('gui ok')"`
Expected: `gui ok` (no NameError/ImportError — confirms `QCheckBox`, `IngestCancelled`, `IndexingDialog`, and the removed `ingest_worker` references are all consistent).

- [ ] **Step 7: Run the whole test suite**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests -q`
Expected: PASS (no regressions).

- [ ] **Step 8: Commit**

```bash
git add Dev/kb_chatbot/gui.py
git commit -m "feat(v2.7): dedicated indexing panel with live progress + per-stage logs; reindex reuses live chroma client

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Manual verification & versioned build (no compile before sandbox sign-off)

> Standing user rule: smoke/sandbox test with explicit confirmation BEFORE building the exe. Do not run the build steps until the user confirms the sandbox run.

- [ ] **Step 1: Run the app from source**

Run: `scraper\venv\Scripts\python.exe Dev\kb_chatbot\gui.py`
Expected: window titled **"Contoso KB Chatbot v2.7"**; chat unlocks quickly (reranker no longer loads at startup).

- [ ] **Step 2: Full index build via the panel**

In the app: confirm the Settings **Library path** is the source `…\Knowledge Base\library\kb` (or `…\library`). Toolbar → **Reindex** → check **Force full rebuild** → **Start**. Watch the live log:
- Confirm the **Tickets** resolved path is `…\library\tickets` and the scan reports ~23,431 ticket files (NOT 0 / NOT a WARNING).
- Confirm the **done** summary shows a non-zero `tickets` count and total chunks in the ~14k+ range.

- [ ] **Step 3: Incremental re-run is fast**

Click **Reindex → Start** again (no force). Expected: completes in seconds, log shows `0 new · 0 changed`, `unchanged` ≈ total file count, `+0 embedded`.

- [ ] **Step 4: Ticket search works**

Ask a question whose answer lives in a ticket resolution. Expected: an answer citing a `Ticket #NNNNN` source — proves tickets are indexed AND retrievable.

- [ ] **Step 5: Codex works**

Settings/dropdown → switch AI Provider to **ChatGPT** (requires `codex login`). Ask any question. Expected: a real answer (no `not valid UTF-8` error in `state/run.log`).

- [ ] **Step 6: STOP — report results to the user and get explicit confirmation to build.**

- [ ] **Step 7: (After confirmation) Build the versioned exe**

Run: `build_chatbot_exe.bat`
Expected: `dist\ContosoKBChatbot-v2.7\ContosoKBChatbot-v2.7.exe` produced.

- [ ] **Step 8: Ship the prebuilt index**

Copy the freshly built index into the onedir output so end users query it without raw tickets:

```bash
cp -r "Dev/kb_chatbot/state/chroma" "dist/ContosoKBChatbot-v2.7/chatbot_state/chroma"
cp "Dev/kb_chatbot/state/chroma/index_manifest.json" "dist/ContosoKBChatbot-v2.7/chatbot_state/chroma/index_manifest.json"
```

(Ensure `dist/ContosoKBChatbot-v2.7/chatbot_state/` exists first; create it if needed.)

- [ ] **Step 9: Launch the exe and confirm**

Run `dist\ContosoKBChatbot-v2.7\ContosoKBChatbot-v2.7.exe`. Expected: title shows **v2.7**, a KB question answers, and a ticket question cites a ticket — from the shipped index, with no reindex needed.

- [ ] **Step 10: Final commit (buglog + docs)**

Append buglog entries for the Codex UTF-8 bug, the silent missing-tickets path bug, and the slow full-rebuild, then:

```bash
git add .wolf/buglog.json docs/superpowers/specs/2026-06-11-kb-chatbot-v2.7-indexing-design.md docs/superpowers/plans/2026-06-11-kb-chatbot-v2.7-indexing.md
git commit -m "docs(v2.7): design + plan + buglog root-cause entries (codex utf-8, missing tickets path, slow rebuild)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the executor

- Run every `pytest` from the repo root with `scraper\venv\Scripts\python.exe -m pytest …`.
- Never `git add -A` / `git add .` blindly — the working tree has pre-existing v2.6 changes; add only the files each task names (Task 7 Step 10's `git add .` lists explicit paths).
- The `collection=` reuse in Task 6 is what fixes the startup `table collections already exists` error: only the Retriever's single client touches the sqlite; the reindex no longer opens a second one.
- If `test_retriever.py` fails referencing `.reranker`, switch that reference to `_get_reranker()` and note it; otherwise leave it untouched.
