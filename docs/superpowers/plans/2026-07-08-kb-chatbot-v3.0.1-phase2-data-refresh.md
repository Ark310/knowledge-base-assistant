# KB Chatbot v3.0.1 — Phase 2: Data Refresh (New tradedesk Ticket Schema) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the chatbot ingest the current portal.contoso.example ticket schema (fixing bug-153), index resolution-less tickets as problem-only (flagged unresolved), move live state off OneDrive, and reindex — so answers are current and cite the right URLs.

**Architecture:** Rewrite `ticket_ingest` to read the new writer schema (`resolution={text,attachments,comments}`, `comments[]={id,author,date,internal,body,...}`, no `type`/`header`). Resolution = `resolution.text` + internal (staff) comment bodies + resolution-thread comments; problem = first non-internal comment or title; a ticket with no resolution is still indexed problem-only with `resolved=False`. Replace real-file-dependent tests with committed PII-free fixtures. `citations.py` is unchanged (it validates by exact URL match against chunk metadata, so re-ingesting with the scraped URLs fixes citations automatically). **Incidents are out of scope** (operator decision — not relevant to the bot).

**Tech Stack:** Python 3.12, pytest (`scraper\venv`), ChromaDB, existing `ticket_redactor`. No new dependencies.

## Global Constraints

- **Test runner:** `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/...`. Imports via `from Dev.kb_chatbot...`.
- **Security unchanged:** every comment/resolution body still passes through `ticket_redactor.redact(...)` with per-ticket `known_terms`. The field-derived staff/client header (`_staff_block`) is never redacted (org name + internal usernames only). Post-ingest secret/PII probe must stay `leaks=0`.
- **Backward-compatible predicates:** a comment counts as a staff/internal note if `c.get("internal")` is truthy OR legacy `c.get("type") == "comment"`; problem = first comment that is neither. This lets any legacy-schema tickets still ingest.
- **No embedder swap.** Reindex is a metadata/text-layout change only → bump `CHUNK_SCHEMA_VERSION` (4 → 5) to force one clean re-embed.
- **State location:** live state (Chroma, chats, usage, caches) moves to `%LOCALAPPDATA%\ContosoKBChatbot` (off OneDrive) with a one-time migration; tests use tempdirs and are unaffected.
- **Operator step:** the actual reindex (and any fresh re-scrape of the live portal) is run by the operator and gated by a smoke test + confirmation before any exe build (standing rule). This plan delivers the code + a runbook, not a live reindex.

---

### Task 1: Move live state off OneDrive (`config.py`)

**Files:**
- Modify: `Dev/kb_chatbot/config.py`
- Test: `Dev/kb_chatbot/tests/test_state_paths.py`

**Interfaces:**
- Produces: `config.STATE_DIR` resolves to `%LOCALAPPDATA%\ContosoKBChatbot` (non-frozen and frozen) with a one-time migration; `config.migrate_state_if_needed(old: Path) -> bool` copies a pre-existing legacy state dir into the new location once. All downstream path constants (`CHROMA_DIR`, `CHATS_DIR`, `USAGE_FILE`, `SETTINGS_FILE`, `ANSWER_CACHE_FILE`, `LOG_FILE`) keep their names, now under the new `STATE_DIR`.

- [ ] **Step 1: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_state_paths.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config


def test_state_dir_is_off_onedrive():
    assert "onedrive" not in str(config.STATE_DIR).lower()

def test_state_children_under_state_dir():
    for p in (config.CHROMA_DIR, config.CHATS_DIR, config.USAGE_FILE,
              config.SETTINGS_FILE, config.ANSWER_CACHE_FILE):
        assert str(p).startswith(str(config.STATE_DIR))

def test_migrate_copies_once(tmp_path, monkeypatch):
    old = tmp_path / "old_state"; (old / "chroma").mkdir(parents=True)
    (old / "chroma" / "x.txt").write_text("hi", encoding="utf-8")
    new = tmp_path / "new_state"
    monkeypatch.setattr(config, "STATE_DIR", new)
    assert config.migrate_state_if_needed(old) is True
    assert (new / "chroma" / "x.txt").read_text(encoding="utf-8") == "hi"
    # second call is a no-op (new already populated)
    assert config.migrate_state_if_needed(old) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_state_paths.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'migrate_state_if_needed'` and the OneDrive assertion fails.

- [ ] **Step 3: Implement in `config.py`**

Replace the freeze-aware base-paths block (the `if getattr(sys, "frozen", False): ... STATE_DIR = ...` section and the path constants that follow) with:
```python
import os
import shutil

# ── Base paths ────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent.parent      # Knowledge Base/

# Live state lives OFF OneDrive (cloud-sync corrupts live SQLite / Chroma).
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
STATE_DIR = Path(_LOCALAPPDATA) / "ContosoKBChatbot"

# Legacy state locations that predate the move (migrated once on startup).
_LEGACY_STATE = (BASE_DIR / "chatbot_state") if getattr(sys, "frozen", False) \
    else (Path(__file__).parent / "state")

LIBRARY_DEFAULT = BASE_DIR / "library" / "kb"
TICKETS_DEFAULT = BASE_DIR / "library" / "tickets"
CHROMA_DIR      = STATE_DIR / "chroma"
CHATS_DIR       = STATE_DIR / "chats"
LOG_FILE        = STATE_DIR / "run.log"
USAGE_FILE      = STATE_DIR / "usage.jsonl"
SETTINGS_FILE   = STATE_DIR / "settings.json"


def migrate_state_if_needed(old) -> bool:
    """One-time copy of a pre-existing legacy state dir into STATE_DIR. Returns
    True if a copy happened, False if skipped (no legacy dir, or new already set up)."""
    old = Path(old)
    if not old.exists():
        return False
    if STATE_DIR.exists() and any(STATE_DIR.iterdir()):
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for child in old.iterdir():
        dest = STATE_DIR / child.name
        try:
            if child.is_dir():
                shutil.copytree(child, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(child, dest)
        except Exception:
            pass
    return True
```
Keep the `ANSWER_CACHE_FILE = STATE_DIR / "answer_cache.json"` line (already added in Phase 1) — it now resolves under the new `STATE_DIR` automatically. (The GUI should call `config.migrate_state_if_needed(config._LEGACY_STATE)` once at startup — that wiring lands in Phase 6; not required for this task's tests.)

- [ ] **Step 4: Run test to verify it passes**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_state_paths.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/tests/test_state_paths.py
git commit -m "feat(v3.0.1-p2): move live state off OneDrive to %LOCALAPPDATA% + one-time migration"
```

---

### Task 2: Rewrite `ticket_ingest` for the new tradedesk schema (+ schema bump)

**Files:**
- Modify: `Dev/kb_chatbot/ticket_ingest.py`
- Modify: `Dev/kb_chatbot/ingest.py` (`CHUNK_SCHEMA_VERSION` 4 → 5)

**Interfaces:**
- Consumes: `ticket_redactor.redact`, `config.normalize_ticket_product`, `_parse_created_at` (unchanged).
- Produces: `build_ticket_chunks(data, path)` reads the new schema; resolution = `resolution.text` + staff (internal / legacy `type=="comment"`) comment bodies + `resolution.comments` bodies; problem = first non-staff comment or title; resolution-less tickets are indexed problem-only with metadata `resolved=False` and a `[UNRESOLVED]` marker in the title line. New metadata key `resolved: bool`. `_known_terms`, `_handled_by`, `has_images` updated to the new schema (no `header` field). Helper `_is_staff_comment(c) -> bool` added.

- [ ] **Step 1: Bump the schema version**

In `Dev/kb_chatbot/ingest.py`, change:
```python
CHUNK_SCHEMA_VERSION = 4  # bump when ticket/article chunk text or metadata layout changes -> forces a clean re-embed
```
to:
```python
CHUNK_SCHEMA_VERSION = 5  # v3.0.1-p2: new tradedesk ticket schema (resolution dict + internal comments) + resolved flag
```

- [ ] **Step 2: Replace the comment-reading helpers in `ticket_ingest.py`**

Replace `_resolution_text`, `_problem_text`, and `_handled_by` (and add `_is_staff_comment`) with:
```python
def _is_staff_comment(c: dict) -> bool:
    """New schema: internal=True marks a Contoso-internal (staff) note. Legacy
    fallback: type == 'comment'."""
    return bool(c.get("internal")) or c.get("type") == "comment"


def _resolution_text(data: dict, known: list[str]) -> str:
    """Redacted resolution: the Resolve field text + internal staff comment bodies
    + resolution-thread comment bodies."""
    parts: list[str] = []
    res = data.get("resolution")
    if isinstance(res, dict):
        t = redact(res.get("text", "") or "", known_terms=known)
        if t:
            parts.append(t)
        for rc in res.get("comments") or []:
            r = redact(rc.get("body", "") or "", known_terms=known)
            if r:
                parts.append(r)
    for c in data.get("comments") or []:
        if _is_staff_comment(c):
            r = redact(c.get("body", "") or "", known_terms=known)
            if r:
                parts.append(r)
    return "\n".join(parts).strip()


def _problem_text(data: dict, known: list[str]) -> str:
    """First non-staff (customer-facing) comment, redacted; else the ticket title."""
    for c in data.get("comments") or []:
        if not _is_staff_comment(c):
            r = redact(c.get("body", "") or "", known_terms=known)
            if r:
                return r
    return redact(data.get("title", "") or "", known_terms=known)


def _handled_by(data: dict) -> list[str]:
    """Internal staff who worked the ticket: staff (internal) comment authors +
    resolution-thread comment authors. Excludes created_by (often the requester)."""
    names: list[str] = []
    for c in data.get("comments") or []:
        if _is_staff_comment(c) and c.get("author"):
            names.append(str(c["author"]))
    res = data.get("resolution")
    if isinstance(res, dict):
        for rc in res.get("comments") or []:
            if rc.get("author"):
                names.append(str(rc["author"]))
    created_by = (data.get("created_by") or "").strip().lower()
    return [n for n in _dedupe_keep_order(names) if n.lower() != created_by]
```
(Delete the now-unused module-level `_BY_SENDER` regex if nothing else references it; if unsure, leave it.)

- [ ] **Step 3: Update `_known_terms` for the header-less schema**

In `_known_terms`, replace the per-comment loop body (the `header`/`combined` section) so it reads `body` only (new schema has no `header`), and also harvest names from the resolution text + resolution comments:
```python
    def _harvest(text: str) -> None:
        for m in _DISPLAY_EMAIL.findall(text):
            terms.append(m); terms.extend(m.split())
        for m in _FROM_NAME.findall(text):
            terms.append(m); terms.extend(m.split())
        for m in _GREET_NAME.findall(text):
            terms.append(m); terms.extend(m.split())
        for m in _CC_NAME.findall(text):
            terms.append(m); terms.extend(m.split())

    for c in data.get("comments", []) or []:
        _harvest((c.get("header", "") or "") + " " + (c.get("body", "") or ""))
    res = data.get("resolution")
    if isinstance(res, dict):
        _harvest(res.get("text", "") or "")
        for rc in res.get("comments") or []:
            _harvest(rc.get("body", "") or "")
```
(Keep the `terms = [created_by, assignee]` seed and the stopword-dedup tail exactly as they are. `_harvest` still tolerates a legacy `header` if present.)

- [ ] **Step 4: Update `build_ticket_chunks` for problem-only + `resolved` + images**

Replace the body of `build_ticket_chunks` from `resolution = _resolution_text(...)` through the end with:
```python
    resolution = _resolution_text(data, known)
    problem = _problem_text(data, known)
    resolved = bool(resolution)
    if not resolution and not problem:
        return []  # genuinely nothing to index

    raw_title = data.get("title", "") or f"Ticket {data.get('ticket_id', '')}"
    raw_project = (data.get("product", "") or "").strip()
    product = config.normalize_ticket_product(raw_project)
    created_at = _parse_created_at(data.get("created_at", ""))
    ticket_id = str(data.get("ticket_id", ""))
    ticket_url = data.get("url", "") or data.get("resolution_url", "")
    resolution_url = data.get("resolution_url", "") or data.get("url", "")
    safe_title = redact(raw_title, known_terms=known) or f"Ticket {ticket_id}"
    handled = _handled_by(data)
    header = _staff_block(data)

    def _has_imgs(comments) -> bool:
        return any((c.get("images") for c in (comments or [])))
    res = data.get("resolution") if isinstance(data.get("resolution"), dict) else {}
    has_images = bool(data.get("attachment_images")) or _has_imgs(data.get("comments")) \
        or _has_imgs(res.get("comments"))

    resolution_block = resolution if resolved else "(no recorded resolution yet — unresolved)"
    body = f"Problem: {problem}\n\nResolution: {resolution_block}"
    segments = _split_words(body, TICKET_CHUNK_WORDS) or [body]
    marker = "" if resolved else " [UNRESOLVED]"
    title_line = f"Ticket #{ticket_id} — {safe_title}{marker}"

    chunks: list[Chunk] = []
    for idx, seg in enumerate(segments):
        text = title_line
        if idx == 0:
            if created_at:
                text += f"\nDate: {created_at}"
            if header:
                text += "\n" + header
        text += "\n\n" + seg
        cid = "ticket_" + hashlib.sha1(
            f"{ticket_id}:{raw_title}:{idx}".encode()).hexdigest()[:16]
        chunks.append(Chunk(
            id=cid,
            text=text,
            metadata={
                "kind": "ticket",
                "product": product,
                "project": raw_project,
                "created_at": created_at,
                "category": data.get("category", "") or "ticket",
                "title": f"Ticket #{ticket_id}",
                "ticket_id": ticket_id,
                "url": ticket_url,
                "resolution_url": resolution_url,
                "organization": data.get("organization", "") or "",
                "csqa_owner": data.get("csqa_owner", "") or "",
                "assignee": data.get("assignee", "") or "",
                "handled_by": ", ".join(handled),
                "has_images": has_images,
                "resolved": resolved,
                "chunk_index": idx,
            },
        ))
    return chunks
```

- [ ] **Step 5: Run the ingest tests (they will need Task 3's rewrite to pass)**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_ingest.py -q`
Expected: the OLD tests may fail here (they assume old-schema fixtures + skip-on-no-resolution). Task 3 rewrites them. Do NOT commit until Task 3 is green. (If you prefer strict TDD, do Task 3's test edits first, then Steps 1-4.)

- [ ] **Step 6: Commit (together with Task 3)**

Commit ingest + tests in one commit at the end of Task 3.

---

### Task 3: New-schema fixtures + rewrite `test_ticket_ingest.py`

**Files:**
- Modify: `Dev/kb_chatbot/tests/test_ticket_ingest.py`

**Interfaces:**
- Consumes: `build_ticket_chunks`, `_known_terms`, `_handled_by`, `_parse_created_at`, `_is_staff_comment`.
- Produces: PII-free, new-schema fixtures built inline (no dependency on the git-ignored real `library/tickets/*.json`).

- [ ] **Step 1: Replace `test_ticket_ingest.py` in full**

```python
import json
from pathlib import Path
from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks


def _ticket(tmp, comments, resolution=None, **over):
    """New tradedesk schema: comments have {author, body, date, internal}; resolution
    is {text, attachments, comments}. All values below are synthetic (no real PII)."""
    data = {"title": "URGENT | CAB FixApp", "product": "TD Client Server",
            "organization": "Fabrikam Financial", "category": "Question",
            "created_by": "srivera", "assignee": "Taylor.Brooks", "status": "Closed",
            "csqa_owner": "p.shah", "ticket_id": "75100",
            "url": "https://portal.contoso.example/tickets/75100/edit",
            "resolution_url": "https://portal.contoso.example/tickets/75100/edit",
            "comments": comments,
            "resolution": resolution if resolution is not None else {"text": "", "attachments": [], "comments": []}}
    data.update(over)
    p = Path(tmp) / "ticket_75100.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return data, p


def test_resolution_from_resolution_text(tmp_path):
    data, p = _ticket(tmp_path,
        [{"author": "srivera", "body": "We are not getting prices from CAB.", "internal": False}],
        resolution={"text": "FixApp session has been restarted", "attachments": [], "comments": []})
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1
    c = chunks[0]
    assert "FixApp session has been restarted" in c.text
    assert c.metadata["resolved"] is True
    assert c.metadata["kind"] == "ticket"
    assert c.metadata["ticket_id"] == "75100"
    assert c.metadata["url"] == data["url"]
    assert c.metadata["title"] == "Ticket #75100"


def test_resolution_from_internal_comment(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "prices missing", "internal": False},
        {"author": "Taylor.Brooks", "body": "Restarted the FixApp session; resolved.", "internal": True},
    ])
    c = build_ticket_chunks(data, p)[0]
    assert "Restarted the FixApp session" in c.text
    assert c.metadata["resolved"] is True


def test_no_resolution_indexes_problem_only(tmp_path):
    data, p = _ticket(tmp_path,
        [{"author": "srivera", "body": "Customer asking a question", "internal": False}])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1                       # NOT skipped anymore
    assert chunks[0].metadata["resolved"] is False
    assert "[UNRESOLVED]" in chunks[0].text
    assert "Customer asking a question" in chunks[0].text


def test_chunk_text_has_no_pii(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera",
         "body": "Hi, From Sam Rivera sam.rivera@fabrikam.example: prices missing. Regards Sam",
         "internal": False},
    ], resolution={"text": "Restarted the session for the client", "attachments": [], "comments": []})
    c = build_ticket_chunks(data, p)[0]
    assert "@" not in c.text
    assert "Sam" not in c.text
    assert "fabrikam" not in c.text.lower()
    assert "Client: Fabrikam Financial" in c.text     # client company surfaced (field-derived header)


def test_stable_id(tmp_path):
    data, p = _ticket(tmp_path, [{"author": "x", "body": "prob", "internal": False}],
                      resolution={"text": "resolved", "attachments": [], "comments": []})
    a = build_ticket_chunks(data, p)[0].id
    b = build_ticket_chunks(data, p)[0].id
    assert a == b and a.startswith("ticket_")


def test_header_surfaces_team_and_client(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "prices missing, please fix", "internal": False},
        {"author": "jchen", "body": "Restarted the session", "internal": True},
    ], resolution={"text": "Fixed on LIVE", "attachments": [], "comments": []},
       csqa_owner="p.shah", sqa_assignee="jchen", site1_qa_signoff="jchen", site2_qa_signoff="p.shah")
    c = build_ticket_chunks(data, p)[0]
    assert "Client: Fabrikam Financial" in c.text
    assert "CSQA owner: p.shah" in c.text
    assert "Assignee: Taylor.Brooks" in c.text
    assert "Handled by:" in c.text and "jchen" in c.text
    assert c.metadata["csqa_owner"] == "p.shah"
    assert c.metadata["organization"] == "Fabrikam Financial"


def test_handled_by_excludes_created_by(tmp_path):
    from Dev.kb_chatbot.ticket_ingest import _handled_by
    data, p = _ticket(tmp_path, [{"author": "srivera", "body": "resolved", "internal": True}],
                      created_by="srivera")
    assert "srivera" not in _handled_by(data)


def test_handled_by_collects_internal_authors(tmp_path):
    from Dev.kb_chatbot.ticket_ingest import _handled_by
    data, p = _ticket(tmp_path, [
        {"author": "customerX", "body": "broke", "internal": False},
        {"author": "jchen", "body": "done", "internal": True},
    ])
    h = _handled_by(data)
    assert "jchen" in h and "customerX" not in h


def test_known_terms_excludes_stopwords_and_org():
    from Dev.kb_chatbot.ticket_ingest import _known_terms
    terms = {t.lower() for t in _known_terms({
        "organization": "Litware", "created_by": "", "assignee": "",
        "comments": [{"author": "a", "body": "Thanks for the update from the bank", "internal": True}],
        "resolution": {"text": "", "comments": []}})}
    assert "for" not in terms and "the" not in terms and "update" not in terms
    assert "litware" not in terms                 # org intentionally not redacted


def test_short_ticket_single_chunk(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "Login fails with error 500.", "internal": False},
        {"author": "a.user", "body": "Cleared the cache; resolved.", "internal": True},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[0].metadata["has_images"] is False
    assert "Problem:" in chunks[0].text and "Resolution:" in chunks[0].text


def test_long_ticket_multi_chunk_shares_ticket_id(tmp_path):
    big = " ".join(f"step{i} do the thing carefully" for i in range(300))
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "It broke.", "internal": False},
        {"author": "a.user", "body": big, "internal": True},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) > 1
    assert all(c.metadata["ticket_id"] == "75100" for c in chunks)
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert all(c.text.startswith("Ticket #75100") for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_has_images_flag_from_comment_images(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "See screenshot.", "internal": False,
         "images": [{"mime": "image/png", "saved_path": "attachments/75100/c1.png"}]},
        {"author": "a.user", "body": "Fixed per the image.", "internal": True},
    ])
    chunks = build_ticket_chunks(data, p)
    assert all(c.metadata["has_images"] is True for c in chunks)


def test_real_corpus_no_email_leak_if_present():
    # Adversarial smoke over any real tickets present locally (git-ignored). Skips if none.
    import glob
    for fp in glob.glob("library/tickets/ticket_*.json")[:50]:
        data = json.loads(Path(fp).read_text(encoding="utf-8"))
        for c in build_ticket_chunks(data, Path(fp)):
            assert "@" not in c.text, f"{fp}: email leaked"


from Dev.kb_chatbot.ticket_ingest import _parse_created_at


def test_parse_created_at_formats():
    assert _parse_created_at("2024-08-22 6:37 AM") == "2024-08-22"
    assert _parse_created_at("2026-04-23 5:41 AM") == "2026-04-23"
    assert _parse_created_at("") == ""
    assert _parse_created_at("garbage") == ""


def test_chunk_has_recency_and_normalized_product(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "It broke.", "internal": False},
        {"author": "a.user", "body": "Fixed it.", "internal": True},
    ], product="FormFlow", created_at="2024-08-22 6:37 AM")
    m = build_ticket_chunks(data, p)[0].metadata
    assert m["product"] == "formflow"
    assert m["project"] == "FormFlow"
    assert m["created_at"] == "2024-08-22"
    assert "Date: 2024-08-22" in build_ticket_chunks(data, p)[0].text
```

- [ ] **Step 2: Run the ingest tests**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_ingest.py -v`
Expected: PASS (all). If a redaction assertion fails, check that `_harvest` runs on the comment `body` (Task 2 Step 3).

- [ ] **Step 3: Commit ingest + tests together**

```bash
git add Dev/kb_chatbot/ticket_ingest.py Dev/kb_chatbot/ingest.py Dev/kb_chatbot/tests/test_ticket_ingest.py
git commit -m "feat(v3.0.1-p2): ingest new tradedesk ticket schema (resolution dict + internal comments, problem-only unresolved) + schema v5"
```

---

### Task 4: Full-suite regression + operator reindex runbook

**Files:**
- Create: `docs/superpowers/plans/REINDEX-v3.0.1.md` (operator runbook)

- [ ] **Step 1: Full suite**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/ -q`
Expected: all pass, including the previously-failing `test_ticket_ingest.py` (now new-schema) and the Phase-1 tests. bug-153 resolved.

- [ ] **Step 2: Write the reindex runbook**

```markdown
# v3.0.1 Reindex (operator)

Phase 2 changed ticket ingestion + bumped CHUNK_SCHEMA_VERSION (4 -> 5), so the
index must be rebuilt once. Optionally re-scrape the live portal first for fresh
data + tradedesk URLs.

1. (Optional, for fresh data) Run the v4 ticket scraper against portal.contoso.example
   into `library/tickets/` (needs portal login).
2. Reindex from source (dev):
   `scraper\venv\Scripts\python.exe -c "from pathlib import Path; from Dev.kb_chatbot.ingest import ingest; print(ingest(Path('library'), Path('<STATE_DIR>/chroma'), force_rebuild=True))"`
   (or use the app's Settings -> Reindex; the schema bump forces a clean re-embed either way).
3. Confirm: ticket chunks now carry `resolved` + tradedesk `url`; run the secret/PII
   probe (scratchpad `_v291_secret_probe.py` style) and confirm `leaks=0`.
4. Smoke a few error questions in the app (both providers), confirm citations resolve
   to portal.contoso.example, THEN rebuild the exe (standing rule: confirm before compile).
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/REINDEX-v3.0.1.md
git commit -m "docs(v3.0.1-p2): operator reindex runbook"
```

---

## Self-Review (completed)

- **Spec coverage (spec §6.2):** re-ingest new portal schema ✓ (T2), stale URLs fixed via re-ingest + exact-match citations ✓ (no citations change needed — verified), state off OneDrive ✓ (T1), reindex + schema bump ✓ (T2 + T4). Recency (`created_at`) preserved ✓. **Incidents intentionally excluded** per operator decision (documented).
- **bug-153:** resolved — new ingest reads the real schema; resolution-less #75100 now yields a problem-only chunk, and the brittle real-file test is replaced by committed fixtures (T3).
- **Placeholder scan:** none — full code for every changed function + the full test file.
- **Type/name consistency:** `_is_staff_comment` (T2) used by `_resolution_text`/`_problem_text`/`_handled_by` (T2) and tested (T3); new metadata key `resolved` set in T2 and asserted in T3; `migrate_state_if_needed` (T1) name matches its test; `CHUNK_SCHEMA_VERSION=5` (T2) is the reindex trigger referenced in T4.
- **Security:** every body still routed through `redact(...)`; `_harvest` covers comment bodies + resolution text/comments; org not redacted; T3 asserts no `@`/name/domain leak; T4 runs the corpus probe.
```
