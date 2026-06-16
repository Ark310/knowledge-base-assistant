# KB Chatbot v2.8 — Internal Resourcing, Client Context & Ticket/KB References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** As an internal-only tool, surface the team members + client behind a ticket and recommend a go-to resource on demand, cite the actual ticket page, and link relevant KB articles in steps — without ever exposing external customer personal PII or secrets.

**Architecture:** Surface staff/client from the **clean structured ticket fields** (added as an un-redacted header to each ticket chunk + as chunk metadata); the existing body PII/secret redaction is left intact as the safety net. The system prompt drives on-demand resourcing (most-frequent CSQA owner across retrieved tickets), client disclosure, escalation, ticket refs, and KB links. A `chunk_schema_version` in the manifest forces a clean re-embed when chunk layout changes.

**Tech Stack:** Python 3, PySide6, chromadb (PersistentClient), sentence-transformers, pytest, PyInstaller.

**Test runner:** `scraper\venv\Scripts\python.exe -m pytest <path> -v` from repo root `C:\Users\AbdulRaqeebKhatri\OneDrive\Documents\Knowledge Base`.

**Branching/commits:** Work on `feat/kb-chatbot-v2.8`. Each task commits only its own files via explicit `git add <paths>`. Commit messages end with the `Co-Authored-By` trailer.

---

## File Structure

- `Dev/kb_chatbot/ticket_ingest.py` — **modify**: add `_staff_block`/`_handled_by`/`_dedupe_keep_order`; drop `organization` from `_known_terms`; rewrite `build_ticket_chunks` (header + metadata + ticket-URL citation).
- `Dev/kb_chatbot/prompt.py` — **modify**: rewrite rule 8, add rules 9–11 (resourcing / client / references+KB-links).
- `Dev/kb_chatbot/ingest.py` — **modify**: `CHUNK_SCHEMA_VERSION` + schema-change force-rebuild.
- `Dev/kb_chatbot/config.py` — **modify**: `APP_VERSION = "2.8"`.
- `build_chatbot_exe.bat` — **modify**: versioned artifact message.
- `Dev/kb_chatbot/tests/test_ticket_ingest.py` — **modify**: update url + org assertions; add header/handled_by/known_terms tests.
- `Dev/kb_chatbot/tests/test_prompt.py` — **modify**: update `test_system_prompt_has_ticket_rule`.
- `Dev/kb_chatbot/tests/test_ingest.py` — **modify**: add schema-version force-rebuild test.
- `Dev/kb_chatbot/tests/test_version.py` — **modify**: assert `"2.8"`.

> `ticket_redactor.py` is intentionally **unchanged** — it redacts whatever `known_terms` it's given plus generic PII/secret patterns; the only policy change (keep the client name) is achieved by dropping `organization` from `_known_terms`.

---

## Task 0: Branch

- [ ] **Step 1: Create the branch** (you are on `master` after the v2.7 merge)

```bash
git checkout -b feat/kb-chatbot-v2.8
```
Expected: `Switched to a new branch 'feat/kb-chatbot-v2.8'`.

---

## Task 1: Ticket chunks — team/client header, ticket-URL citation, keep client name

**Files:**
- Modify: `Dev/kb_chatbot/ticket_ingest.py`
- Test: `Dev/kb_chatbot/tests/test_ticket_ingest.py`

- [ ] **Step 1: Update the existing tests to the new behavior**

In `Dev/kb_chatbot/tests/test_ticket_ingest.py`:

(a) In `test_chunk_has_problem_and_resolution`, change the URL assertion from the resolution URL to the **ticket** URL:
```python
    assert c.metadata["url"] == data["url"]
    assert c.metadata["resolution_url"] == data["resolution_url"]
```

(b) In `test_chunk_text_has_no_pii`, the client company name is now **surfaced** (only the customer's personal name/email/domain stay stripped). Replace its assertions block with:
```python
    c = build_ticket_chunks(data, p)[0]
    assert "@" not in c.text                       # emails still stripped
    assert "Sam" not in c.text                    # external customer personal name stripped
    assert "fabrikam" not in c.text.lower()   # email domain stripped
    assert "Client: Fabrikam Financial" in c.text      # client company name now surfaced
```

(c) In `test_real_ticket_chunks_no_pii`, the org is no longer forbidden; keep only the hard email guarantee. Replace the inner loop body with:
```python
        for c in chunks:
            assert "@" not in c.text, f"{tid}: email leaked"
```

- [ ] **Step 2: Add new tests for the header, handled_by, and known_terms**

Append to `Dev/kb_chatbot/tests/test_ticket_ingest.py`:
```python
def test_chunk_header_surfaces_team_and_client(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "unknown", "body": "prices missing, please fix"},
        {"type": "comment", "author": "jchen", "body": "Restarted the session"},
        {"type": "unknown",
         "header": "email 1 sent to A Customer <c@client.com> by mlopez on 2023-01-01"},
    ], csqa_owner="p.shah", sqa_assignee="jchen", site1_qa_signoff="jchen",
       site2_qa_signoff="p.shah")
    c = build_ticket_chunks(data, p)[0]
    assert "Client: Fabrikam Financial" in c.text
    assert "CSQA owner: p.shah" in c.text
    assert "Assignee: Taylor.Brooks" in c.text
    assert "Handled by:" in c.text and "jchen" in c.text and "mlopez" in c.text
    assert c.metadata["csqa_owner"] == "p.shah"
    assert c.metadata["organization"] == "Fabrikam Financial"
    assert c.metadata["url"] == data["url"]


def test_handled_by_excludes_created_by(tmp_path):
    # created_by is often the external requester — never list it as a resource.
    data, p = _ticket(tmp_path, [
        {"type": "comment", "author": "srivera", "body": "resolved"},
    ], created_by="srivera")
    from Dev.kb_chatbot.ticket_ingest import _handled_by
    assert "srivera" not in _handled_by(data)


def test_known_terms_excludes_organization():
    from Dev.kb_chatbot.ticket_ingest import _known_terms
    terms = {t.lower() for t in _known_terms(
        {"organization": "Litware", "created_by": "", "assignee": "", "comments": []})}
    assert "litware" not in terms
```

- [ ] **Step 3: Run the tests to verify they FAIL**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_ingest.py -v`
Expected: failures — `_staff_block`/`_handled_by` not defined, url still resolution, org still stripped.

- [ ] **Step 4: Drop `organization` from `_known_terms`**

In `Dev/kb_chatbot/ticket_ingest.py`, replace:
```python
    terms: list[str] = [
        data.get("organization", "") or "",
        data.get("created_by", "") or "",
        data.get("assignee", "") or "",
    ]
```
with:
```python
    # v2.8: organization is intentionally NOT redacted — this is an internal tool and
    # the client company name is surfaced (also in the structured header). created_by +
    # assignee stay so personal names in the body are still stripped; the surfaced
    # team/client come from _staff_block (fields), not the redacted body.
    terms: list[str] = [
        data.get("created_by", "") or "",
        data.get("assignee", "") or "",
    ]
```

- [ ] **Step 5: Add the field-derived helpers**

In `Dev/kb_chatbot/ticket_ingest.py`, insert these definitions just above `def build_ticket_chunks(`:
```python
_BY_SENDER = re.compile(r"\bby\s+([a-z][\w.\-]+)")  # "...sent to <customer> by mlopez"


def _dedupe_keep_order(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        v = (v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _handled_by(data: dict) -> list[str]:
    """Internal staff who worked the ticket: comment authors + the 'by <user>'
    sender on outbound (sent-to) email headers. Excludes created_by, which is
    often the external requester."""
    names: list[str] = []
    for c in data.get("comments", []):
        if c.get("type") == "comment" and c.get("author"):
            names.append(str(c["author"]))
        header = c.get("header") or ""
        if "sent to" in header.lower():
            m = _BY_SENDER.search(header)
            if m:
                names.append(m.group(1))
    created_by = (data.get("created_by") or "").strip().lower()
    return [n for n in _dedupe_keep_order(names) if n.lower() != created_by]


def _staff_block(data: dict) -> str:
    """Field-derived, un-redacted team/client header. Contains only the client
    company name + internal staff usernames — never customer-individual PII."""
    lines: list[str] = []
    org = (data.get("organization") or "").strip()
    if org:
        lines.append(f"Client: {org}")
    parts: list[str] = []
    owner = (data.get("csqa_owner") or "").strip()
    if owner:
        parts.append(f"CSQA owner: {owner}")
    assignee = (data.get("assignee") or "").strip()
    if assignee:
        parts.append(f"Assignee: {assignee}")
    qa = _dedupe_keep_order([data.get("sqa_assignee"), data.get("site1_qa_signoff"),
                             data.get("site2_qa_signoff")])
    if qa:
        parts.append("QA sign-off: " + ", ".join(qa))
    handled = _handled_by(data)
    if handled:
        parts.append("Handled by: " + ", ".join(handled))
    if parts:
        lines.append(" · ".join(parts))
    return "\n".join(lines)
```

- [ ] **Step 6: Rewrite `build_ticket_chunks`**

Replace the whole `build_ticket_chunks` function with:
```python
def build_ticket_chunks(data: dict, path) -> list[Chunk]:
    """Return at most one Chunk for the ticket. Skips tickets with no internal
    resolution comment. The chunk carries a field-derived team/client header and
    cites the actual ticket page (not the resolution page)."""
    known = _known_terms(data)
    resolution = _resolution_text(data, known)
    if not resolution:
        return []

    problem = _problem_text(data, known)
    raw_title = data.get("title", "") or f"Ticket {data.get('ticket_id', '')}"
    product = data.get("product", "") or "tickets"
    ticket_id = str(data.get("ticket_id", ""))
    ticket_url = data.get("url", "") or data.get("resolution_url", "")
    resolution_url = data.get("resolution_url", "") or data.get("url", "")

    safe_title = redact(raw_title, known_terms=known) or f"Ticket {ticket_id}"
    header = _staff_block(data)

    text = f"Ticket #{ticket_id} — {safe_title}"
    if header:
        text += "\n" + header
    text += f"\n\nProblem: {problem}\n\nResolution: {resolution}"

    cid = "ticket_" + hashlib.sha1(f"{ticket_id}:{raw_title}".encode()).hexdigest()[:16]

    return [Chunk(
        id=cid,
        text=text,
        metadata={
            "kind": "ticket",
            "product": product,
            "category": data.get("category", "") or "ticket",
            "title": f"Ticket #{ticket_id}",
            "ticket_id": ticket_id,
            "url": ticket_url,                # v2.8: link to the ticket itself
            "resolution_url": resolution_url,
            "organization": data.get("organization", "") or "",
            "csqa_owner": data.get("csqa_owner", "") or "",
            "assignee": data.get("assignee", "") or "",
            "handled_by": ", ".join(_handled_by(data)),
            "chunk_index": 0,
        },
    )]
```

- [ ] **Step 7: Run the ticket-ingest tests — all PASS**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_ingest.py Dev/kb_chatbot/tests/test_ticket_redactor.py -v`
Expected: all pass (updated + new ingest tests; the unchanged redactor tests still pass).

- [ ] **Step 8: Commit**

```bash
git add Dev/kb_chatbot/ticket_ingest.py Dev/kb_chatbot/tests/test_ticket_ingest.py
git commit -m "feat(v2.8): ticket chunks surface client + team (field-derived header), cite the actual ticket page; drop org from redaction terms

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: System prompt — internal resourcing, client, references + KB links

**Files:**
- Modify: `Dev/kb_chatbot/prompt.py`
- Test: `Dev/kb_chatbot/tests/test_prompt.py`

- [ ] **Step 1: Update the ticket-rule test to the new guardrail wording**

In `Dev/kb_chatbot/tests/test_prompt.py`, replace `test_system_prompt_has_ticket_rule` with:
```python
def test_system_prompt_has_ticket_rule():
    from Dev.kb_chatbot.prompt import build_system_prompt
    p = build_system_prompt().lower()
    assert "ticket" in p
    # internal tool: customer PERSONAL contact details still protected
    assert "customer" in p and ("personal" in p or "contact details" in p)
    # resourcing + escalation wording present
    assert "csqa owner" in p
    assert "team lead" in p or "senior resource" in p
```

- [ ] **Step 2: Run it to verify it FAILS**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_prompt.py::test_system_prompt_has_ticket_rule -v`
Expected: FAIL (current prompt has none of "csqa owner"/"team lead").

- [ ] **Step 3: Rewrite the ticket rule + add resourcing/client/reference rules**

In `Dev/kb_chatbot/prompt.py`, replace exactly this block (the current rule 8):
```python
8. CONTEXT may include past support tickets (labelled "Ticket #<id>"). If a ticket resolved a similar issue, you may present its resolution and cite it as [Ticket #<id>](url) using the exact URL from CONTEXT. Never include customer names, emails, phone numbers, or company names — they are not in CONTEXT and must never be invented.

Do not editorialise. Do not apologise. Do not speculate. Do not summarise articles that were not retrieved."""
```
with:
```python
8. CONTEXT may include past support tickets (labelled "Ticket #<id>"), each with a header line listing Client, CSQA owner, Assignee, QA sign-off, and Handled by. This is an INTERNAL tool: you MAY name the client (company) and internal Contoso staff (by their usernames) from that header when relevant, and cite the ticket as [Ticket #<id>](url) using the exact URL from CONTEXT. You must NEVER reveal an external customer individual's personal contact details (their personal name, personal email, or phone number) or any password/secret/API key, and never invent any of these.
9. Resourcing — ONLY when the user asks who to contact or who handled an issue: recommend the CSQA owner who appears across the most relevant tickets first, then the Assignee / QA sign-off, then staff who Handled it; name them by username and cite the ticket(s). If no owner is recorded or you cannot tell, say: "I don't have an owner on record — consult a team lead or a senior resource." Do not volunteer resourcing in normal answers.
10. Client — ONLY when the user asks which client an issue occurred at: name the Client from the relevant ticket header; if it is not recorded, say to check with a team lead. Do not volunteer the client otherwise.
11. References: when a step comes from a specific ticket, append "(Ticket #<id>)" to that step, and end the answer with a "Sources: #<id>, ..." line. Where a step is also covered by a KB how-to, topic, or release note present in CONTEXT, link it as [Title](url) too.

Do not editorialise. Do not apologise. Do not speculate. Do not summarise articles that were not retrieved."""
```

- [ ] **Step 4: Run the full prompt test file — all PASS**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_prompt.py -v`
Expected: all pass. (`test_system_prompt_locked_text_v23` and `test_system_prompt_demands_completeness` still pass — rules 1–7 and the phrases "Contoso KB articles", "I don't have enough information in the knowledge base", "[Article Title](url)", "ALL relevant", "only use facts from the CONTEXT" are unchanged.)

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/prompt.py Dev/kb_chatbot/tests/test_prompt.py
git commit -m "feat(v2.8): prompt rules for on-demand team resourcing (CSQA owner first), client disclosure, escalation, ticket refs + KB links; keep customer-PII/secret floor

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Reindex correctness — `chunk_schema_version`

**Files:**
- Modify: `Dev/kb_chatbot/ingest.py`
- Test: `Dev/kb_chatbot/tests/test_ingest.py`

- [ ] **Step 1: Write the failing test**

Append to `Dev/kb_chatbot/tests/test_ingest.py`:
```python
def test_chunk_schema_change_forces_rebuild(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    mf = chroma / "index_manifest.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data.get("chunk_schema_version") is not None  # written on ingest
    data["chunk_schema_version"] = 0                      # simulate an older schema
    mf.write_text(json.dumps(data), encoding="utf-8")
    r2 = ingest(lib, chroma)
    assert r2.chunks_embedded == r1.chunks_embedded       # all re-embedded
```

- [ ] **Step 2: Run it to verify it FAILS**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ingest.py::test_chunk_schema_change_forces_rebuild -v`
Expected: FAIL (no `chunk_schema_version` written; r2 embeds 0).

- [ ] **Step 3: Add the constant**

In `Dev/kb_chatbot/ingest.py`, after `MANIFEST_NAME = "index_manifest.json"` add:
```python
CHUNK_SCHEMA_VERSION = 2  # bump when ticket/article chunk text or metadata layout changes -> forces a clean re-embed
```

- [ ] **Step 4: Wire the schema-change force-rebuild**

Replace this block in `ingest()`:
```python
        # -- Now safe to clear for a full rebuild / embed-model change ---------
        model_changed = manifest.get("embed_model") not in ("", config.EMBED_MODEL)
        if force_rebuild or model_changed:
            ids = collection.get(include=[]).get("ids", [])
            for i in range(0, len(ids), DELETE_BATCH):
                collection.delete(ids=ids[i:i + DELETE_BATCH])
            manifest = {"version": 1, "embed_model": config.EMBED_MODEL, "files": {}}
        manifest["embed_model"] = config.EMBED_MODEL
        files = manifest["files"]
```
with:
```python
        # -- Now safe to clear for a full rebuild / embed-model / schema change -
        model_changed = manifest.get("embed_model") not in ("", config.EMBED_MODEL)
        schema_changed = bool(manifest.get("files")) and \
            manifest.get("chunk_schema_version") != CHUNK_SCHEMA_VERSION
        if force_rebuild or model_changed or schema_changed:
            ids = collection.get(include=[]).get("ids", [])
            for i in range(0, len(ids), DELETE_BATCH):
                collection.delete(ids=ids[i:i + DELETE_BATCH])
            manifest = {"version": 1, "embed_model": config.EMBED_MODEL,
                        "chunk_schema_version": CHUNK_SCHEMA_VERSION, "files": {}}
        manifest["embed_model"] = config.EMBED_MODEL
        manifest["chunk_schema_version"] = CHUNK_SCHEMA_VERSION
        files = manifest["files"]
```

- [ ] **Step 5: Run the ingest tests — all PASS**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ingest.py -v`
Expected: all pass (new schema test + existing incremental/guard tests — a normal second run still embeds 0 because the version now matches).

- [ ] **Step 6: Commit**

```bash
git add Dev/kb_chatbot/ingest.py Dev/kb_chatbot/tests/test_ingest.py
git commit -m "feat(v2.8): chunk_schema_version in manifest forces re-embed when chunk layout changes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Version bump to 2.8

**Files:**
- Modify: `Dev/kb_chatbot/config.py`, `build_chatbot_exe.bat`
- Test: `Dev/kb_chatbot/tests/test_version.py`

- [ ] **Step 1: Update the version test**

In `Dev/kb_chatbot/tests/test_version.py`, change:
```python
def test_app_version_is_2_7():
    assert config.APP_VERSION == "2.7"
```
to:
```python
def test_app_version_is_2_8():
    assert config.APP_VERSION == "2.8"
```

- [ ] **Step 2: Run it — FAILS**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_version.py -v`
Expected: FAIL (APP_VERSION is "2.7").

- [ ] **Step 3: Bump the version**

In `Dev/kb_chatbot/config.py`, change `APP_VERSION = "2.7"` to `APP_VERSION = "2.8"`.

In `build_chatbot_exe.bat`, change the final echo to reference `ContosoKBChatbot-v2.8` (folder + exe).

- [ ] **Step 4: Run it — PASS**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_version.py -v`
Expected: PASS. (The `.spec` reads `APP_VERSION`, so the exe/folder become `ContosoKBChatbot-v2.8` automatically.)

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/config.py build_chatbot_exe.bat Dev/kb_chatbot/tests/test_version.py
git commit -m "chore(v2.8): bump APP_VERSION to 2.8

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full-suite check, security re-probe, verify, build (build only after user sign-off)

> Standing rule: sandbox test with explicit user confirmation BEFORE building the exe.

- [ ] **Step 1: Full test suite green**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests -q`
Expected: all pass.

- [ ] **Step 2: Rebuild the index from source (forces re-embed via the schema bump)**

Run the app from source: `scraper\venv\Scripts\python.exe Dev\kb_chatbot\gui.py`
In Settings, set **KB source folder** to the real `…\Knowledge Base\library`. Toolbar → **Reindex** → **Start** (the `chunk_schema_version` bump triggers a full rebuild automatically; **Force full rebuild** also works). Confirm the Done summary shows the full ticket count.

- [ ] **Step 3: Full-corpus PII re-probe (external emails/phones/secrets must NOT leak; org + usernames allowed)**

Run this throwaway probe from the repo root:
```bash
scraper\venv\Scripts\python.exe -c "import json,glob,re; from pathlib import Path; from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks; EMAIL=re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'); PHONE=re.compile(r'\+?\d[\d\s().\-]{7,}\d'); leaks=0; n=0;\nfor f in glob.glob('library/tickets/ticket_*.json'):\n  d=json.loads(Path(f).read_text(encoding='utf-8'));\n  for c in build_ticket_chunks(d,Path(f)):\n    n+=1;\n    if EMAIL.search(c.text) or PHONE.search(c.text): leaks+=1; print('LEAK',f)\nprint('chunks',n,'leaky',leaks)"
```
Expected: `leaky 0`. (Internal usernames + client company names are allowed and expected; emails/phones are not.) If any leak prints, STOP and fix before building.

- [ ] **Step 4: Source-run scenario check (manual)**

With the app running, confirm:
1. "How do I remove a duplicate entity in TradeDesk?" → steps + `(Ticket #N)` + a `Sources:` line; KB `[Title](url)` links where present; **no** team/client volunteered.
2. "Who should I ask about duplicate-entity removal?" → most-frequent CSQA owner first (username), then assignee/QA/handled-by, with ticket refs; if none → "consult a team lead / senior resource."
3. "Which client had this issue?" → client company name; if unknown → check with a lead.
4. "What's the customer's email/phone on that ticket?" → declined; offers the internal owner.
5. Click a ticket citation → opens the **ticket** page (`edit_bug.aspx?id=N`), not the resolution page.

- [ ] **Step 5: STOP — report results to the user and get explicit confirmation to build.**

- [ ] **Step 6: (After confirmation) Build the versioned exe**

Run: `scraper\venv\Scripts\python.exe -m PyInstaller ContosoKBChatbot.spec --noconfirm --workpath build_v28 --distpath dist`
(Fresh `--workpath` avoids the OneDrive `--clean` WinError 5.)
Expected: `dist\ContosoKBChatbot-v2.8\ContosoKBChatbot-v2.8.exe`.

- [ ] **Step 7: Ship the rebuilt index**

```bash
mkdir -p "dist/ContosoKBChatbot-v2.8/chatbot_state"
cp -r "Dev/kb_chatbot/state/chroma" "dist/ContosoKBChatbot-v2.8/chatbot_state/chroma"
```
Verify: `scraper\venv\Scripts\python.exe -c "import chromadb;print(chromadb.PersistentClient(path=r'dist/ContosoKBChatbot-v2.8/chatbot_state/chroma').get_collection('kbs').count())"` → non-zero.

- [ ] **Step 8: Launch the exe and confirm** title `v2.8`, a resourcing question, a client question, and a ticket citation that opens the ticket page.

- [ ] **Step 9: Final docs commit**

```bash
git add docs/superpowers/specs/2026-06-12-kb-chatbot-v2.8-internal-resourcing-design.md docs/superpowers/plans/2026-06-12-kb-chatbot-v2.8-internal-resourcing.md
git commit -m "docs(v2.8): design spec + implementation plan

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the executor

- Run every `pytest` from the repo root with `scraper\venv\Scripts\python.exe -m pytest …`.
- Never `git add -A`/`git add .` — the working tree has pre-existing unrelated changes; add only the files each task names.
- `ticket_redactor.py` stays unchanged — the only redaction policy change is dropping `organization` from `_known_terms`.
- The structured header is built from raw fields and is never passed through `redact()`; it must only ever contain the org name + internal usernames (the probe in Step 3 gates this).
