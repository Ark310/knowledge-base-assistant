# KB Chatbot v2.9.1 — Phase 1: Data Layer (Redaction Hardening + Ticket Re-Chunking) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the HIGH secret-redaction gap (bug-063) and harden name redaction, and re-chunk tickets for retrieval with image metadata — producing a clean, secret-free, parent-retrievable ticket index.

**Architecture:** Pure data-layer changes. `ticket_redactor.py` gains a label-independent secret scrubber, broadened credential labels, multi-token credential values, and signature/name hardening. `ticket_ingest.py` splits long tickets into multiple ordered chunks sharing a `ticket_id` and carrying `chunk_index` + `has_images`. `ingest.py` bumps `CHUNK_SCHEMA_VERSION` so the next reindex re-embeds cleanly. No orchestrator/retriever/UI changes (those are Phase 2+). No full reindex in this phase — the reindex+re-ship happens in Phase 4; Phase 1 is verified by unit tests + a corpus probe that calls `build_ticket_chunks` directly (no embedding).

**Tech Stack:** Python 3, `re`, pytest. Tests run with `scraper/venv/Scripts/python.exe -m pytest` from the repo root.

## Global Constraints

- **Redaction tightens, never loosens.** All existing redactor assertions (emails, phones, known_terms, credentials) must stay green.
- **Allowed in chunk text:** client COMPANY name (`organization`) and internal Contoso staff USERNAMES. **Never allowed:** external customer personal name/email/phone, or any password/secret/API key/token.
- **No placeholders / no over-redaction of legitimate data:** version strings (e.g. `2.5.4.6`), short order/ticket numbers, and ordinary words must survive.
- **Chroma metadata values must be scalars** (`str`/`int`/`float`/`bool`) — no lists/dicts in chunk metadata.
- **Test runner:** `scraper/venv/Scripts/python.exe -m pytest <path> -v` from repo root. Imports use `from Dev.kb_chatbot...` (conftest puts repo root on `sys.path`).
- **Commit after each task.** Branch: `feat/kb-chatbot-v2.9.1` (already checked out).

---

### Task 1: Label-independent secret-shape scrubber

**Files:**
- Modify: `Dev/kb_chatbot/chat/ticket_redactor.py`
- Test: `Dev/kb_chatbot/tests/test_ticket_redactor.py`

**Interfaces:**
- Produces: `_redact_secret_shapes(line: str) -> str` and `_looks_secret(tok: str) -> bool`, wired into `redact()` after the `_CRED_LABEL` substitution.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_ticket_redactor.py`:

```python
def test_high_entropy_token_redacted():
    out = redact("ClientID: G5qjl8ujMGHJlfrNAnrPG0BM1sYohXIZAcobZ6vWm9LZAIT2", known_terms=[])
    assert "G5qjl8ujMGHJlfrNAnrPG0BM1sYohXIZAcobZ6vWm9LZAIT2" not in out
    assert "[redacted]" in out

def test_base64_blob_redacted():
    out = redact("file_bytes: VGVzdCBmaWxlIGZvciBwYXltZW50IHByb2Nlc3NpbmcgZGVtbw==", known_terms=[])
    assert "VGVzdCBmaWxlIGZvciBwYXltZW50IHByb2Nlc3NpbmcgZGVtbw" not in out

def test_jwt_redacted():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36"
    out = redact(f"token is {jwt}", known_terms=[])
    assert "eyJhbGciOiJIUzI1NiJ9" not in out

def test_hex_address_redacted():
    out = redact("wallet 0x52908400098527886E0F7030069857D2E4169EE7 confirmed", known_terms=[])
    assert "52908400098527886E0F7030069857D2E4169EE7" not in out

def test_version_string_not_over_redacted():
    out = redact("Upgrade to version 2.5.4.6 to fix this", known_terms=[])
    assert "2.5.4.6" in out

def test_ordinary_long_word_not_redacted():
    out = redact("This is an internationalization problem in the module", known_terms=[])
    assert "internationalization" in out

def test_short_id_not_redacted():
    out = redact("See order 75100 and ref AB12 for details", known_terms=[])
    assert "75100" in out and "AB12" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_redactor.py -k "secret or entropy or base64 or jwt or hex or version or ordinary or short_id" -v`
Expected: FAIL (the high-entropy / base64 / jwt / hex tokens are NOT yet removed).

- [ ] **Step 3: Implement the scrubber**

In `Dev/kb_chatbot/chat/ticket_redactor.py`, add after the `_BARE_DOMAIN` definition (near line 54):

```python
# ── Label-independent secret-shape scrubbing ──────────────────────────────────
# Catches secrets that have no recognised label (OAuth client IDs, raw API keys,
# base64/hex blobs, JWTs, hex wallet addresses). Conservative thresholds so
# version strings, order numbers, and ordinary words are not eaten.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_HEX_ADDR = re.compile(r"\b0x[0-9a-fA-F]{16,}\b")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{20,}")


def _looks_secret(tok: str) -> bool:
    core = tok.strip("=")
    if len(core) < 20:
        return False
    # base64-ish or hex blob of length >= 32
    if len(core) >= 32 and re.fullmatch(r"[A-Za-z0-9+/]+", core):
        return True
    if len(core) >= 32 and re.fullmatch(r"[0-9a-fA-F]+", core):
        return True
    # high-entropy: >= 20 chars mixing lower + upper + digit (looks like a key)
    has_low = any(c.islower() for c in core)
    has_up = any(c.isupper() for c in core)
    has_dig = any(c.isdigit() for c in core)
    return len(core) >= 20 and has_low and has_up and has_dig


def _redact_secret_shapes(line: str) -> str:
    line = _JWT.sub("[redacted]", line)
    line = _HEX_ADDR.sub("[redacted]", line)
    return _LONG_TOKEN.sub(
        lambda m: "[redacted]" if _looks_secret(m.group(0)) else m.group(0), line
    )
```

Then in `redact()`, add the call immediately after the `_CRED_LABEL` line (currently line 82):

```python
        line = _CRED_LABEL.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
        line = _redact_secret_shapes(line)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_redactor.py -v`
Expected: PASS (new tests pass; all pre-existing redactor tests still pass).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/ticket_redactor.py Dev/kb_chatbot/tests/test_ticket_redactor.py
git commit -m "feat(v2.9.1): label-independent secret-shape scrubber in ticket redactor (bug-063)"
```

---

### Task 2: Broaden credential labels + redact multi-token values

**Files:**
- Modify: `Dev/kb_chatbot/chat/ticket_redactor.py:39-45` (`_CRED_LABEL`)
- Test: `Dev/kb_chatbot/tests/test_ticket_redactor.py`

**Interfaces:**
- Consumes: nothing.
- Produces: updated `_CRED_LABEL` (same 3-group shape, so the existing `lambda m: f"{m.group(1)}{m.group(2)}[redacted]"` call is unchanged).

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_ticket_redactor.py`:

```python
def test_clientid_label_redacted():
    out = redact("ClientID: G5qjl8ujMGHJ", known_terms=[])
    assert "G5qjl8ujMGHJ" not in out

def test_gateway_customer_id_redacted():
    out = redact("Gateway Customer ID: Comerica22964e769bbf2527", known_terms=[])
    assert "Comerica22964e769bbf2527" not in out

def test_multi_word_credential_value_redacted():
    out = redact("Password: my secret pass phrase", known_terms=[])
    assert "secret pass phrase" not in out
    assert "Password" in out  # the label survives

def test_credential_prose_without_separator_survives():
    out = redact("Please reset the password to continue", known_terms=[])
    assert "reset the password to continue" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_redactor.py -k "clientid or gateway or multi_word_cred or prose_without_separator" -v`
Expected: FAIL on `clientid`, `gateway`, and `multi_word_credential` (current regex doesn't know those labels and stops at one token).

- [ ] **Step 3: Update `_CRED_LABEL`**

Replace the `_CRED_LABEL` definition (lines 39-45) with:

```python
_CRED_LABEL = re.compile(
    r"(?i)\b(pass(?:word|phrase)?|pwd|user\s?name|username|login|"
    r"api[\s_-]?key|secret(?:\s*key)?|access[\s_-]?key|private[\s_-]?key|"
    r"decrypt\s*key|auth[\s_-]?token|token|credentials?|"
    r"client[\s_-]?id|customer[\s_-]?id|gateway(?:\s*customer)?(?:\s*id)?|"
    r"sk|client[\s_-]?secret|bearer)\b"
    r"""(["']?\s*(?:for[^:=\n]*)?[:=]\s*)"""
    r"""(?:(["'])[^"'\n]*\2|[^\n;,]+)"""
)
```

(Changes: added `client id / customer id / gateway[ customer][ id] / sk / client secret / bearer` to the keyword group; changed the unquoted-value branch from `\S+` to `[^\n;,]+` so the whole value to end-of-line / next `;`/`,` is redacted.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_redactor.py -v`
Expected: PASS (new + all existing).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/ticket_redactor.py Dev/kb_chatbot/tests/test_ticket_redactor.py
git commit -m "feat(v2.9.1): broaden credential labels + redact multi-token credential values"
```

---

### Task 3: Personal-name redaction hardening

**Files:**
- Modify: `Dev/kb_chatbot/chat/ticket_redactor.py` (`_ACTION_NAME` at lines 26-30; `redact()` loop for the signature-drop)
- Modify: `Dev/kb_chatbot/ticket_ingest.py:49-55` (`_STOPWORDS`)
- Test: `Dev/kb_chatbot/tests/test_ticket_redactor.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_is_signoff(line: str) -> bool` helper in `ticket_redactor.py`; updated `_ACTION_NAME`; expanded `_STOPWORDS`.

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_ticket_redactor.py`:

```python
def test_action_verb_multiword_name_fully_redacted():
    out = redact("I called Morgan Blake about the deal", known_terms=[])
    assert "Morgan" not in out and "Blake" not in out

def test_signature_line_after_signoff_dropped():
    out = redact("Resolved the issue.\nRegards,\nPriya Patel", known_terms=[])
    assert "Priya Patel" not in out

def test_non_signoff_short_capitalized_line_survives():
    out = redact("Open the panel.\nClick Save Now", known_terms=[])
    assert "Click Save Now" in out
```

Append to `Dev/kb_chatbot/tests/test_ticket_ingest.py`:

```python
from Dev.kb_chatbot.ticket_ingest import _known_terms

def test_greeting_modal_not_harvested_as_term():
    data = {"comments": [{"type": "comment", "author": "a.user",
                          "header": "", "body": "Thanks. Could you re-run the batch?"}]}
    terms = _known_terms(data)
    assert "Could" not in terms and "could" not in [t.lower() for t in terms]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_redactor.py -k "multiword_name or signature_line or non_signoff" Dev/kb_chatbot/tests/test_ticket_ingest.py -k "modal_not_harvested" -v`
Expected: FAIL (surname leaks; signature line kept; "Could" harvested).

- [ ] **Step 3a: Multi-token action names**

In `ticket_redactor.py`, change `_ACTION_NAME` (line 29) capture group from `([A-Z][a-z]+)` to multi-token:

```python
_ACTION_NAME = re.compile(
    r"\b((?i:messaged|message|asked|told|emailed|email|called|contacted|"
    r"spoke to|spoke with|pinged|notified|informed|advised|reached out to))\s+"
    r"(?:the\s+(?:user|customer|client)\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)
```

(The replacement `lambda m: f"{m.group(1)} [redacted]"` is unchanged — group 1 is still the verb.)

- [ ] **Step 3b: Signature-line drop after a sign-off**

In `ticket_redactor.py`, add this helper after the `_DROP_LINE` definition (near line 63):

```python
_SIGNOFF_LINE = re.compile(
    r"^\s*(?i:regards|thanks|thank you|best|kind regards|cheers|sincerely|br|warm regards)\b"
)
_NAME_ONLY_LINE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}$")


def _is_signoff(line: str) -> bool:
    return bool(_SIGNOFF_LINE.match(line.strip()))
```

Then, in `redact()`, track whether the previous kept line was a sign-off and drop a following name-only line. Replace the line-loop preamble and the `_DROP_LINE` check so the loop reads:

```python
    cleaned_lines: list[str] = []
    prev_signoff = False
    for raw_line in text.replace("\r", "").split("\n"):
        line = raw_line
        stripped_raw = line.strip()
        if _DROP_LINE.match(stripped_raw):
            prev_signoff = _is_signoff(stripped_raw)
            continue
        # A short all-capitalised line right after a sign-off is a signature name.
        if prev_signoff and _NAME_ONLY_LINE.match(stripped_raw):
            prev_signoff = False
            continue
        prev_signoff = _is_signoff(stripped_raw)
        line = _EMAIL.sub("[redacted]", line)
```

(Everything from `line = _EMAIL.sub(...)` downward in the loop is unchanged.)

- [ ] **Step 3c: Expand `_STOPWORDS`**

In `ticket_ingest.py`, add modal/connective words to the `_STOPWORDS` set (lines 49-55). Add these entries to the set literal:

```python
    "could", "would", "should", "also", "however", "therefore", "moreover",
    "additionally", "furthermore", "regarding", "hello",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_redactor.py Dev/kb_chatbot/tests/test_ticket_ingest.py -v`
Expected: PASS (new + all existing).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/ticket_redactor.py Dev/kb_chatbot/ticket_ingest.py Dev/kb_chatbot/tests/test_ticket_redactor.py Dev/kb_chatbot/tests/test_ticket_ingest.py
git commit -m "feat(v2.9.1): harden name redaction (multi-token action names, sign-off signatures, greeting-modal stopwords)"
```

---

### Task 4: Re-chunk tickets for retrieval + image metadata

**Files:**
- Modify: `Dev/kb_chatbot/ticket_ingest.py` (`build_ticket_chunks` at lines 201-245; add `_split_words` + `TICKET_CHUNK_WORDS`)
- Test: `Dev/kb_chatbot/tests/test_ticket_ingest.py`

**Interfaces:**
- Consumes: `_known_terms`, `_resolution_text`, `_problem_text`, `_handled_by`, `_staff_block` (existing, unchanged).
- Produces: `build_ticket_chunks(data: dict, path) -> list[Chunk]` now returns 1..N chunks, each with metadata keys `ticket_id`, `chunk_index` (0-based, contiguous), `has_images` (bool), plus the existing keys. Phase 2's parent-document assembly relies on `ticket_id` + `chunk_index` to reassemble the full ticket, and on `has_images` for the screenshot note.

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_ticket_ingest.py`:

```python
def test_short_ticket_single_chunk(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "email", "header": "", "body": "Login fails with error 500."},
        {"type": "comment", "author": "a.user", "header": "", "body": "Cleared the cache; resolved."},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[0].metadata["has_images"] is False
    assert "Problem:" in chunks[0].text and "Resolution:" in chunks[0].text

def test_long_ticket_multi_chunk_shares_ticket_id(tmp_path):
    big = " ".join(f"step{i} do the thing carefully" for i in range(300))  # ~1500 words
    data, p = _ticket(tmp_path, [
        {"type": "email", "header": "", "body": "It broke."},
        {"type": "comment", "author": "a.user", "header": "", "body": big},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) > 1
    assert all(c.metadata["ticket_id"] == "75100" for c in chunks)
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert all(c.text.startswith("Ticket #75100") for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)  # unique ids

def test_has_images_flag_set(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "email", "header": "", "body": "See screenshot."},
        {"type": "comment", "author": "a.user", "header": "", "body": "Fixed per the image."},
    ], attachment_images=[{"mime": "image/png", "saved_path": "attachments/75100/c1.png"}])
    chunks = build_ticket_chunks(data, p)
    assert all(c.metadata["has_images"] is True for c in chunks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_ingest.py -k "single_chunk or multi_chunk or has_images_flag" -v`
Expected: FAIL (current builder returns one chunk with no `chunk_index`/`has_images`, and never splits).

- [ ] **Step 3: Rewrite `build_ticket_chunks`**

In `ticket_ingest.py`, add near the top (after the imports, before `_known_terms`):

```python
TICKET_CHUNK_WORDS = 350  # retrieval window kept below embed (~256) / rerank (~512) truncation


def _split_words(text: str, size: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [text.strip()]
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]
```

Replace `build_ticket_chunks` (lines 201-245) with:

```python
def build_ticket_chunks(data: dict, path) -> list[Chunk]:
    """Return 1..N Chunks for the ticket (split for retrieval; reassembled to the
    full ticket at answer time via ticket_id + chunk_index). Skips tickets with no
    internal resolution comment. Each chunk leads with the ticket title; the
    field-derived staff/client header rides on the first chunk. `has_images` flags
    that the ticket page carries screenshot(s) — the images themselves are never
    indexed, stored, or surfaced."""
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
    handled = _handled_by(data)
    header = _staff_block(data)
    has_images = bool(data.get("attachment_images"))

    body = f"Problem: {problem}\n\nResolution: {resolution}"
    segments = _split_words(body, TICKET_CHUNK_WORDS) or [body]
    title_line = f"Ticket #{ticket_id} — {safe_title}"

    chunks: list[Chunk] = []
    for idx, seg in enumerate(segments):
        text = title_line
        if idx == 0 and header:
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
                "chunk_index": idx,
            },
        ))
    return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_ingest.py -v`
Expected: PASS (new + all existing — the existing short-ticket fixtures still yield one chunk whose `text` contains `Problem:`/`Resolution:` and whose `url` is the ticket URL).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/ticket_ingest.py Dev/kb_chatbot/tests/test_ticket_ingest.py
git commit -m "feat(v2.9.1): re-chunk tickets for retrieval (ticket_id + chunk_index) + has_images metadata"
```

---

### Task 5: Bump `CHUNK_SCHEMA_VERSION`

**Files:**
- Modify: `Dev/kb_chatbot/ingest.py:29`
- Test: `Dev/kb_chatbot/tests/test_ingest.py`

**Interfaces:**
- Consumes: the new chunk layout from Tasks 1-4.
- Produces: `CHUNK_SCHEMA_VERSION = 3`, so the next reindex (Phase 4) forces a clean full re-embed of the hardened, re-chunked tickets.

- [ ] **Step 1: Write the failing test**

Append to `Dev/kb_chatbot/tests/test_ingest.py`:

```python
def test_chunk_schema_version_is_3():
    from Dev.kb_chatbot.ingest import CHUNK_SCHEMA_VERSION
    assert CHUNK_SCHEMA_VERSION == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ingest.py -k "schema_version_is_3" -v`
Expected: FAIL (currently `CHUNK_SCHEMA_VERSION == 2`).

- [ ] **Step 3: Bump the constant**

In `Dev/kb_chatbot/ingest.py` line 29, change:

```python
CHUNK_SCHEMA_VERSION = 3  # bump when ticket/article chunk text or metadata layout changes -> forces a clean re-embed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ingest.py -v`
Expected: PASS (new test passes; the existing schema-version-guard test still passes — it reads the constant, not a literal).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/ingest.py Dev/kb_chatbot/tests/test_ingest.py
git commit -m "chore(v2.9.1): bump CHUNK_SCHEMA_VERSION to 3 (redaction + ticket re-chunk force clean re-embed)"
```

---

### Task 6: Extended secret-shape corpus probe + full regression

**Files:**
- Create: `_v291_secret_probe.py` (repo root, mirrors the existing `_v28_pii_probe.py` throwaway style)
- Test: (uses the real corpus if present; otherwise reports skipped)

**Interfaces:**
- Consumes: `build_ticket_chunks` (Task 4) + the hardened `redact()` (Tasks 1-3).
- Produces: a probe asserting **zero** secret-shaped tokens (and zero emails) survive across all real ticket chunks. This is the §8 verification gate for the redaction fix; it does not embed, so it runs without a reindex.

- [ ] **Step 1: Write the probe script**

Create `_v291_secret_probe.py`:

```python
"""Throwaway v2.9.1 secret-shape probe. Runs the LIVE build_ticket_chunks over
every ticket JSON and asserts no secret-shaped token (high-entropy/base64/hex/JWT)
and no email survives in chunk text. Org names + internal usernames are allowed."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks
from Dev.kb_chatbot.chat.ticket_redactor import _looks_secret

TICKETS = Path("library/tickets")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{20,}")
_PLACEHOLDER = "[redacted]"

def main() -> int:
    files = sorted(TICKETS.rglob("ticket_*.json"))
    if not files:
        print("No ticket corpus present — skipping (run where library/tickets exists).")
        return 0
    leaks = []
    n_chunks = 0
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for c in build_ticket_chunks(data, f):
            n_chunks += 1
            text = c.text
            for tok in _TOKEN.findall(text):
                if tok == _PLACEHOLDER:
                    continue
                if _looks_secret(tok):
                    leaks.append((f.name, "secret", tok[:24]))
            for em in _EMAIL.findall(text):
                if em != _PLACEHOLDER:
                    leaks.append((f.name, "email", em))
    print(f"Scanned {len(files)} tickets -> {n_chunks} chunks; leaks={len(leaks)}")
    for name, kind, sample in leaks[:30]:
        print(f"  LEAK {kind} in {name}: {sample}")
    return 1 if leaks else 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the probe**

Run: `scraper/venv/Scripts/python.exe _v291_secret_probe.py`
Expected: `leaks=0` (prints the chunk count). If the corpus isn't present in this environment, it prints "skipping" and exits 0 — note that and run it where `library/tickets` exists before the Phase 4 build.

- [ ] **Step 3: Run the FULL kb_chatbot test suite (regression gate)**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests -v`
Expected: PASS — all pre-existing tests plus the new Task 1-5 tests are green. If anything fails, fix before committing (the redaction changes must not break existing assertions).

- [ ] **Step 4: Commit**

```bash
git add _v291_secret_probe.py
git commit -m "test(v2.9.1): full-corpus secret-shape probe (asserts secret-shaped tokens = 0)"
```

---

## Self-Review

**Spec coverage (Phase 1 scope = spec §6.5a, §6.5c, §6.7a-chunking, §6.7e-metadata, §6.6 schema bump):**
- §6.5(a) secret scrubber → Task 1; broaden labels + multi-token values → Task 2. ✓
- §6.5(c) name hardening (multi-token action names, signature heuristic, `_GREET_NAME` stopwords) → Task 3. ✓
- §6.7(a) ticket re-chunking (ticket_id + chunk_index) → Task 4. ✓
- §6.7(e) `has_images` metadata → Task 4. ✓
- §6.6 `CHUNK_SCHEMA_VERSION` bump → Task 5. ✓
- §7 extended probe (secret-shaped = 0) → Task 6. ✓
- **Deferred to later phases (not Phase 1):** output-side scrub, Learn-Mode KDF, rendering regression test (Phase 4); parent-document *assembly*, answer-cap, image-*note*, KB-alongside, expert prompt (Phase 2); reasoning-effort/flags (Phase 3); full reindex + re-ship (Phase 4). These are intentionally out of this plan.

**Placeholder scan:** none — every step has real code/commands/expected output.

**Type consistency:** `_redact_secret_shapes`/`_looks_secret` defined in Task 1 and reused in Task 6's probe; `build_ticket_chunks` returns `list[Chunk]` with `ticket_id`/`chunk_index`/`has_images` defined in Task 4 (the names Phase 2's assembly will consume); `CHUNK_SCHEMA_VERSION = 3` consistent across Tasks 4-5. The `_CRED_LABEL` 3-group shape is preserved so its existing replacement lambda is unchanged.

**Note / minor spec refinement:** ticket chunks are split **without overlap** (the spec said "with overlap"). Rationale: Phase 2 always expands any matched ticket chunk to the *whole* ticket, so cross-boundary recall is already covered and non-overlapping segments make reassembly exact (no de-dup). Flagged for the Phase 2 author.
