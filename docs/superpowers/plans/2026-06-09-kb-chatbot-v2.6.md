# KB Chatbot v2.6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix ChatGPT/Codex execution in the frozen exe (surface its errors), improve accuracy (recalibrated sigmoid abstain floor + stronger prompt), add support tickets as a PII-redacted retrieval source with clickable ticket/resolution references, and ship a one-folder build that launches instantly with offline bundled models.

**Architecture:** All changes layer on current master (v2.5). Codex error handling hardens the existing subprocess provider. Accuracy is a scoring/prompt change (no new deps, no v3 machinery). Tickets add two small new modules (redactor + ticket chunker) feeding the existing ChromaDB ingest/retrieve pipeline. Packaging changes the PyInstaller spec to one-folder + bundled offline models.

**Tech Stack:** PySide6, ChromaDB, sentence-transformers, claude-agent-sdk, Codex CLI, PyInstaller. Python 3.12.

**Working directory:** repo root. **Branch:** `feature/kb-chatbot-v2.6`. **Test command:** `& "scraper\venv\Scripts\python.exe" -m pytest <path> -v`

**Hard constraint:** ticket data contains customer PII; org policy forbids surfacing it. The redactor is the safety layer — its tests are mandatory gates.

---

## File Map

| File | Status | Responsibility |
|------|--------|----------------|
| `llm/codex_provider.py` | Modify | `CodexExecError`; raise (not blank) on non-zero/empty; log stderr; `-C` safe cwd |
| `retriever.py` | Modify | `_sigmoid`; normalize rerank score to 0–1; new floor |
| `config.py` | Modify | `CONFIDENCE_FLOOR` 0.06; `CLARIFY_SCORE_FLOOR` 0.0; `TICKETS_DEFAULT` |
| `chat/orchestrator.py` | Modify | re-express drift + low-confidence thresholds on 0–1 |
| `prompt.py` | Modify | completeness directives; ticket context label + ticket citation rule |
| `chat/ticket_redactor.py` | **New** | `redact()` — strip PII conservatively |
| `ticket_ingest.py` | **New** | `build_ticket_chunks()` — redacted problem+resolution chunks |
| `ingest.py` | Modify | also ingest `library/tickets/*.json` (redacted) |
| `llm/claude_code_provider.py` | Modify | `cli_path=shutil.which("claude")` in options |
| `ContosoKBChatbot.spec` | Modify | one-folder `COLLECT`; bundle model caches; exclude `_bundled` |
| `gui.py` | Modify | HF offline env before model imports; InitWorker stage text |
| `build_chatbot_exe.bat` | Modify | folder-output note |
| `tests/test_codex_provider.py` | Modify | error-surfacing tests |
| `tests/test_retriever_floor.py` | **New** | sigmoid + floor tests |
| `tests/test_ticket_redactor.py` | **New** | PII never survives |
| `tests/test_ticket_ingest.py` | **New** | chunk shape/metadata/resolution |
| `tests/test_citations.py` | Modify | ticket-link citation |

---

## Task 1: Codex error surfacing (§1a)

**Files:** Modify `Dev/kb_chatbot/llm/codex_provider.py`; Test `Dev/kb_chatbot/tests/test_codex_provider.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_codex_provider.py`:

```python
def test_run_codex_exec_raises_on_nonzero_return(monkeypatch):
    class _Proc:
        stdout = ""
        stderr = "boom: codex blew up\nmore detail"
        returncode = 1
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", lambda *a, **k: _Proc())
    try:
        cp._run_codex_exec("prompt", "gpt-5.4-mini")
        assert False, "expected CodexExecError"
    except cp.CodexExecError as e:
        assert "boom" in str(e)


def test_run_codex_exec_raises_on_empty_output(monkeypatch):
    class _Proc:
        stdout = '{"type":"turn.started"}'   # no agent_message, no usage
        stderr = ""
        returncode = 0
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", lambda *a, **k: _Proc())
    # also stub the -o file read to empty by pointing tempfile at a path the proc never writes
    try:
        cp._run_codex_exec("prompt", "gpt-5.4-mini")
        assert False, "expected CodexExecError"
    except cp.CodexExecError:
        pass


def test_run_codex_exec_logs_stderr_not_prompt(monkeypatch, caplog):
    class _Proc:
        stdout = ""
        stderr = "stderr-secret-reason"
        returncode = 2
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", lambda *a, **k: _Proc())
    import logging as _l
    with caplog.at_level(_l.WARNING):
        try:
            cp._run_codex_exec("SENSITIVE-PROMPT-TEXT", "gpt-5.4-mini")
        except cp.CodexExecError:
            pass
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "stderr-secret-reason" in joined
    assert "SENSITIVE-PROMPT-TEXT" not in joined
```

- [ ] **Step 2: Run — expect failures** (`CodexExecError` undefined; current code returns blank instead of raising).
`& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_codex_provider.py -k "raises or logs" -v`

- [ ] **Step 3: Implement in `codex_provider.py`.** Add the error class after `CodexNotFoundError`:

```python
class CodexExecError(RuntimeError):
    """Raised when `codex exec` exits non-zero or produces no answer."""
```

In `_run_codex_exec`, replace the body after `proc = subprocess.run(...)` (the text-read + usage-parse + estimate-fallback + return) with:

```python
        try:
            with open(out_path, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
        except Exception:
            text = ""
        if not text:
            text = _extract_agent_message(proc.stdout).strip()
        tin, tout = _parse_usage(proc.stdout)

        if proc.returncode != 0 or not text:
            stderr_tail = (proc.stderr or "").strip()[:300]
            log.warning("codex exec failed: rc=%s stderr=%s", proc.returncode, stderr_tail)
            raise CodexExecError(
                f"codex exec failed (rc={proc.returncode}): "
                f"{stderr_tail or 'no output produced'}"
            )

        if not tin and not tout:
            tin = max(1, len(prompt) // 4)
            tout = max(1, len(text) // 4)
        return text, tin, tout
```

(The `finally:` that unlinks `out_path` stays. Note: the prompt text is NEVER logged — only `stderr_tail`.)

Also add a safe working directory to avoid the spaces-in-cwd hypothesis: in the `cmd`/`args` build, after `--ephemeral`, add `"-C", tempfile.gettempdir()`. So:
```python
    args = ["exec", "-m", model, "--json",
            "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
            "-C", tempfile.gettempdir(),
            "-o", out_path]
```

- [ ] **Step 4: Run** `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_codex_provider.py -v` → all pass (existing `test_chat_stubbed_subprocess` still passes: its fake proc returns rc 0 and writes the `-o` file, so text is non-empty).

- [ ] **Step 5: Commit**
```
git add Dev/kb_chatbot/llm/codex_provider.py Dev/kb_chatbot/tests/test_codex_provider.py
git commit -m "fix(v2.6): surface codex exec failures (raise+log stderr) instead of blank; safe -C cwd"
```

> §1b (the precise frozen-exe cause) is finalized in Task 8 from the real captured stderr.

---

## Task 2: Accuracy — sigmoid abstain floor (§2a)

**Files:** Modify `retriever.py`, `config.py`, `chat/orchestrator.py`; Test `Dev/kb_chatbot/tests/test_retriever_floor.py` (new)

- [ ] **Step 1: Write failing tests** — create `tests/test_retriever_floor.py`:

```python
import math
from Dev.kb_chatbot.retriever import _sigmoid


def test_sigmoid_zero():
    assert abs(_sigmoid(0.0) - 0.5) < 1e-9


def test_sigmoid_monotonic_and_bounded():
    assert _sigmoid(-1.334) < 0.5 < _sigmoid(2.0)
    assert 0.0 < _sigmoid(-12.0) < _sigmoid(11.0) < 1.0


def test_sigmoid_matches_formula():
    for x in (-3.0, -1.334, 0.0, 0.5, 4.0):
        assert abs(_sigmoid(x) - 1 / (1 + math.exp(-x))) < 1e-9
```

- [ ] **Step 2: Run — expect ImportError** (`_sigmoid` undefined).

- [ ] **Step 3: Implement in `retriever.py`.** Add at module level (after imports):
```python
import math


def _sigmoid(x: float) -> float:
    """Map a CrossEncoder logit to a 0–1 probability for a stable abstain floor."""
    if x < 0:
        z = math.exp(x)
        return z / (1.0 + z)
    return 1.0 / (1.0 + math.exp(-x))
```
In `retrieve()`, change the scoring block so the floor compares the NORMALIZED score and the stored `rerank_top_score` is the 0–1 value:
```python
        top = scored[: self.top_k_rerank]
        raw_top = float(top[0][1]) if top else -99.0
        top_score = _sigmoid(raw_top)   # 0–1

        if top_score < self.confidence_floor:
            log.info("Abstaining: top score %.3f (logit %.3f) < floor %.3f",
                     top_score, raw_top, self.confidence_floor)
            return RetrievalResult(
                chunks=[], raw_top_score=raw_top,
                rerank_top_score=top_score, abstain_reason="no_relevant_kb_match",
            )

        return RetrievalResult(
            chunks=[c for c, _ in top], raw_top_score=raw_top, rerank_top_score=top_score,
        )
```
(`scored` ordering is unchanged — sigmoid is monotonic, so the selected chunks are identical; only the gate scale changes.)

- [ ] **Step 4: Update `config.py`** — change the floor and clarify constant:
```python
CONFIDENCE_FLOOR    = 0.06   # sigmoid(rerank logit); was 0.30 on raw logits (over-abstained)
CLARIFY_SCORE_FLOOR = 0.0    # rerank score is now 0–1; 0.0 keeps the abstain-path clarify check live
```

- [ ] **Step 5: Update `chat/orchestrator.py` thresholds to the 0–1 scale.** Change the three constants:
```python
_DRIFT_PREVIOUS_FLOOR = 0.85   # 0–1 sigmoid: previous turn was confident
_DRIFT_CURRENT_CEILING = 0.20  # 0–1 sigmoid: current turn very low
```
and
```python
LOW_CONFIDENCE_CEILING = 0.35   # 0–1 sigmoid: append suggestion footer below this
```

- [ ] **Step 6: Run tests** — new floor tests + the orchestrator/multi-turn suites (they stub `RetrievalResult` directly with explicit scores, so update any that assumed logit-scale numbers):
```
& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_retriever_floor.py Dev/kb_chatbot/tests/test_retriever.py Dev/kb_chatbot/tests/test_orchestrator.py Dev/kb_chatbot/tests/test_query_rewriter.py -v
```
If a test in `test_retriever.py` or `test_orchestrator.py` constructs `RetrievalResult(rerank_top_score=0.35, ...)` or asserts a logit-scale score expecting the OLD low-confidence behaviour, adjust its score to the new 0–1 intent (e.g. a "low-confidence answer" uses 0.20; a "high-confidence" uses 0.90). Keep each test's INTENT; only move the number onto the 0–1 scale.

- [ ] **Step 7: Commit**
```
git add Dev/kb_chatbot/retriever.py Dev/kb_chatbot/config.py Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/
git commit -m "fix(v2.6): sigmoid-normalize rerank score; recalibrate abstain floor (0.30 logit -> 0.06 prob)"
```

---

## Task 3: Accuracy — prompt completeness (§2b)

**Files:** Modify `prompt.py`

- [ ] **Step 1: Write the test** — append to `Dev/kb_chatbot/tests/test_prompt.py`:
```python
def test_system_prompt_demands_completeness():
    from Dev.kb_chatbot.prompt import build_system_prompt
    p = build_system_prompt().lower()
    assert "all relevant" in p or "every step" in p
    # guardrails still present
    assert "only use facts from the context" in p
    assert "[article title](url)" in p
```

- [ ] **Step 2: Run — expect failure** (completeness phrase not present).

- [ ] **Step 3: Implement** — in `prompt.py`, replace rule 6 and the trailing paragraph of `SYSTEM_PROMPT`:

Current:
```
6. Format the answer as: one-sentence direct answer first; then bullet list of relevant steps (each with citation link); then a "Searched:" footnote naming the product(s) considered.

Do not editorialise. Do not apologise. Do not speculate. Do not summarise articles that were not retrieved.
```
New:
```
6. Be COMPLETE: use ALL relevant CONTEXT entries, not just the first. For a procedure, include EVERY step, parameter, and field present in the context, in their original order, and never truncate a procedure midway.
7. Format: one-sentence direct answer first; then the full steps as a numbered list (each factual claim ending with its [Title](url) citation); then a "Searched:" footnote naming the product(s) considered.

Do not editorialise. Do not apologise. Do not speculate. Do not summarise articles that were not retrieved."""
```
(Keep rules 1–5 unchanged. Ensure the closing triple-quote remains correct.)

- [ ] **Step 4: Run** `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_prompt.py -v` → pass.

- [ ] **Step 5: Commit**
```
git add Dev/kb_chatbot/prompt.py Dev/kb_chatbot/tests/test_prompt.py
git commit -m "feat(v2.6): strengthen system prompt for answer completeness"
```

---

## Task 4: Ticket redactor (§3a)

**Files:** Create `Dev/kb_chatbot/chat/ticket_redactor.py`; Test `Dev/kb_chatbot/tests/test_ticket_redactor.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_ticket_redactor.py`:
```python
from Dev.kb_chatbot.chat.ticket_redactor import redact


def test_emails_removed():
    out = redact("Contact sam.rivera@fabrikam.example please", known_terms=[])
    assert "@" not in out
    assert "sam.rivera" not in out


def test_phones_removed():
    out = redact("Call +44 (0)20 7350 5473 or 020 3992 9579", known_terms=[])
    assert "7350" not in out and "3992" not in out


def test_known_terms_removed_case_insensitive():
    out = redact("Issue reported by Fabrikam Financial via sam", known_terms=["Fabrikam Financial", "Sam"])
    assert "Fabrikam Financial" not in out
    assert "fabrikam financial" not in out.lower()
    assert "sam" not in out.lower()


def test_boilerplate_lines_dropped():
    txt = ("Subject: RE: ticket\n"
           "To: 'Contoso Support' <user@contoso.example>\n"
           "attachment: text.html view savesize: 26331 content-type: text/html\n"
           "FixApp session has been restarted")
    out = redact(txt, known_terms=[])
    assert "FixApp session has been restarted" in out
    assert "Subject:" not in out
    assert "attachment:" not in out


def test_real_sample_no_pii(tmp_path):
    import json
    from pathlib import Path
    base = Path("library/tickets/ticket_75100.json")
    data = json.loads(base.read_text(encoding="utf-8"))
    known = [data.get("organization",""), data.get("created_by",""), data.get("assignee","")]
    bodies = "\n".join(c.get("body","") for c in data.get("comments", []))
    out = redact(bodies, known_terms=[k for k in known if k])
    assert "@" not in out
    assert "Fabrikam Financial" not in out
    assert "fabrikam" not in out.lower()
```

- [ ] **Step 2: Run — expect ModuleNotFoundError.**

- [ ] **Step 3: Create `Dev/kb_chatbot/chat/ticket_redactor.py`:**
```python
"""Conservative PII redaction for support-ticket text.

Org policy forbids surfacing customer PII. This strips emails, phone numbers,
known person/org terms, and email/signature boilerplate BEFORE any ticket text
is indexed or shown. When a line still looks like contact/signature noise after
inline redaction, it is dropped. Conservative by design: prefer dropping to leaking."""
from __future__ import annotations
import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")
_URL = re.compile(r"https?://\S+")

# Lines that are pure email/quote/signature boilerplate → dropped entirely.
_DROP_LINE = re.compile(
    r"^\s*(subject:|to:|cc:|bcc:|from:|sent:|date:|attachment:|"
    r"registered|authorised by|authorized by|privacy policy|"
    r"important this email|confidential|view our|connect on linkedin|"
    r"t:|e:|w:|tel:|phone:|mobile:|fax:)",
    re.IGNORECASE,
)


def redact(text: str, *, known_terms: list[str]) -> str:
    """Return text with PII removed. known_terms (org/person names from the
    ticket's own fields) are removed case-insensitively as whole words."""
    if not text:
        return ""
    term_res = [
        re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)
        for t in known_terms if t and len(t) >= 2
    ]
    cleaned_lines: list[str] = []
    for raw_line in text.replace("\r", "").split("\n"):
        line = raw_line
        if _DROP_LINE.match(line.strip()):
            continue
        line = _EMAIL.sub("[redacted]", line)
        line = _URL.sub("[link]", line)
        line = _PHONE.sub("[redacted]", line)
        for tr in term_res:
            line = tr.sub("[redacted]", line)
        # Drop a line that became mostly redaction markers or is now noise.
        stripped = line.strip()
        if not stripped:
            continue
        cleaned_lines.append(line)
    out = "\n".join(cleaned_lines)
    # Collapse runs of whitespace introduced by inline subs.
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()
```

- [ ] **Step 4: Run** `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_ticket_redactor.py -v` → all pass. (If the real-sample test surfaces a leaked token, tighten `_DROP_LINE`/patterns until it passes — the test is the gate.)

- [ ] **Step 5: Commit**
```
git add Dev/kb_chatbot/chat/ticket_redactor.py Dev/kb_chatbot/tests/test_ticket_redactor.py
git commit -m "feat(v2.6): conservative PII redactor for ticket text"
```

---

## Task 5: Ticket ingestion (§3b)

**Files:** Create `Dev/kb_chatbot/ticket_ingest.py`; Modify `ingest.py`, `config.py`; Test `Dev/kb_chatbot/tests/test_ticket_ingest.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_ticket_ingest.py`:
```python
import json
from pathlib import Path
from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks


def _ticket(tmp, comments, **over):
    data = {"title": "URGENT | CAB FixApp", "product": "TD Client Server",
            "organization": "Fabrikam Financial", "category": "Question",
            "created_by": "srivera", "assignee": "Taylor.Brooks", "status": "Closed",
            "ticket_id": "75100", "url": "https://support.contoso.example/edit_bug.aspx?id=75100",
            "resolution_url": "https://support.contoso.example/Resolution.aspx?bugid=75100",
            "comments": comments}
    data.update(over)
    p = Path(tmp) / "ticket_75100.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return data, p


def test_chunk_has_problem_and_resolution(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "unknown", "body": "We are not getting prices from CAB. Please restart FixApp."},
        {"type": "comment", "author": "Taylor.Brooks", "body": "FixApp session has been restarted"},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1
    c = chunks[0]
    assert "FixApp session has been restarted" in c.text
    assert c.metadata["kind"] == "ticket"
    assert c.metadata["ticket_id"] == "75100"
    assert c.metadata["url"] == data["resolution_url"]   # citation validates against url
    assert c.metadata["resolution_url"] == data["resolution_url"]


def test_chunk_text_has_no_pii(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "unknown", "body": "From Sam Rivera sam.rivera@fabrikam.example: prices missing"},
        {"type": "comment", "author": "Taylor.Brooks", "body": "Restarted the session"},
    ])
    c = build_ticket_chunks(data, p)[0]
    assert "@" not in c.text
    assert "Fabrikam Financial" not in c.text
    assert "fabrikam" not in c.text.lower()


def test_no_resolution_skipped(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "unknown", "body": "Customer asking a question"},
    ])
    assert build_ticket_chunks(data, p) == []


def test_stable_id(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "comment", "author": "x", "body": "resolved"},
    ])
    a = build_ticket_chunks(data, p)[0].id
    b = build_ticket_chunks(data, p)[0].id
    assert a == b and a.startswith("ticket_")
```

- [ ] **Step 2: Run — expect ModuleNotFoundError.**

- [ ] **Step 3: Create `Dev/kb_chatbot/ticket_ingest.py`:**
```python
"""Build PII-redacted retrieval chunks from support tickets.

Each ticket yields at most one chunk: title + redacted problem + redacted
resolution. Tickets with no usable internal resolution are skipped. The chunk's
`url` metadata is the resolution_url so the existing citation validator works
unchanged."""
from __future__ import annotations
import hashlib
import re

from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.chat.ticket_redactor import redact

_NAME_HINTS = re.compile(r"\b(?:Hi|Hello|Dear|from|regards|thanks),?\s+([A-Z][a-z]+)")


def _known_terms(data: dict) -> list[str]:
    terms = [data.get("organization", ""), data.get("created_by", ""),
             data.get("assignee", "")]
    for c in data.get("comments", []):
        for m in _NAME_HINTS.findall(c.get("body", "") or ""):
            terms.append(m)
        hdr = c.get("header", "") or ""
        for m in re.findall(r"from ([A-Z][a-z]+ [A-Z][a-z]+)", hdr):
            terms.extend(m.split())
    return [t for t in terms if t]


def _resolution_text(data: dict, known: list[str]) -> str:
    """Concatenate redacted internal staff comments (the resolution)."""
    parts = []
    for c in data.get("comments", []):
        if c.get("type") == "comment" and c.get("author"):
            r = redact(c.get("body", "") or "", known_terms=known)
            if r:
                parts.append(r)
    return "\n".join(parts).strip()


def _problem_text(data: dict, known: list[str]) -> str:
    for c in data.get("comments", []):
        if c.get("type") != "comment":
            r = redact(c.get("body", "") or "", known_terms=known)
            if r:
                return r
    return redact(data.get("title", "") or "", known_terms=known)


def build_ticket_chunks(data: dict, path) -> list[Chunk]:
    known = _known_terms(data)
    resolution = _resolution_text(data, known)
    if not resolution:
        return []   # no resolution → not useful as a "how it was solved" reference
    problem = _problem_text(data, known)
    title = data.get("title", "") or f"Ticket {data.get('ticket_id','')}"
    product = data.get("product", "") or "tickets"
    ticket_id = str(data.get("ticket_id", ""))
    resolution_url = data.get("resolution_url", "") or data.get("url", "")

    text = f"Ticket #{ticket_id}: {title}\n\nProblem: {problem}\n\nResolution: {resolution}"
    cid = "ticket_" + hashlib.sha1(f"{ticket_id}:{title}".encode()).hexdigest()[:16]
    return [Chunk(
        id=cid,
        text=text,
        metadata={
            "kind": "ticket",
            "product": product,
            "category": data.get("category", "") or "ticket",
            "title": f"Ticket #{ticket_id}",
            "ticket_id": ticket_id,
            "url": resolution_url,            # citation validates against this
            "resolution_url": resolution_url,
            "chunk_index": 0,
        },
    )]
```

- [ ] **Step 4: Run** `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_ticket_ingest.py -v` → pass.

- [ ] **Step 5: Wire into `ingest.py` + `config.py`.** In `config.py` add near `LIBRARY_DEFAULT`:
```python
TICKETS_DEFAULT = BASE_DIR / "library" / "tickets"
```
In `ingest.py`, add an import and a gather+build for tickets. After `from Dev.kb_chatbot.chunker import build_article_chunks, Chunk` add:
```python
from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks
```
Add a helper:
```python
def _gather_ticket_jsons(tickets_path: Path) -> list[Path]:
    if not tickets_path.exists():
        return []
    return [p for p in sorted(tickets_path.glob("*.json")) if p.name != "index.json"]
```
In `ingest()`, give it an optional tickets path (default derived from the kb library's sibling) and ingest tickets alongside articles. Change the signature and add the ticket loop after the article loop (before the `total = len(all_chunks)` line):
```python
def ingest(
    library_path: Path,
    chroma_path: Path,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    tickets_path: Path | None = None,
) -> IngestReport:
```
and after the article `for f in files:` loop:
```python
    tpath = tickets_path if tickets_path is not None else (library_path.parent / "tickets")
    for tf in _gather_ticket_jsons(tpath):
        try:
            tdata = json.loads(tf.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Skipping unreadable ticket %s: %s", tf, exc)
            report.skipped += 1
            continue
        tchunks = build_ticket_chunks(tdata, tf)
        if tchunks:
            report.articles_seen += 1
            report.products["tickets"] = report.products.get("tickets", 0) + 1
            all_chunks.extend(tchunks)
        else:
            report.skipped += 1
```

- [ ] **Step 6: Add an ingest integration test** — append to `tests/test_ticket_ingest.py`:
```python
def test_ingest_picks_up_tickets(tmp_path, monkeypatch):
    # tickets dir as sibling of an empty kb dir
    import json as _j
    kb = tmp_path / "kb"; kb.mkdir()
    tickets = tmp_path / "tickets"; tickets.mkdir()
    (tickets / "ticket_1.json").write_text(_j.dumps({
        "title": "T", "product": "tradedesk", "ticket_id": "1",
        "resolution_url": "https://support.contoso.example/Resolution.aspx?bugid=1",
        "comments": [{"type": "comment", "author": "a", "body": "did the fix"}],
    }), encoding="utf-8")
    from Dev.kb_chatbot.ingest import _gather_ticket_jsons
    found = _gather_ticket_jsons(tickets)
    assert len(found) == 1
```

Run it; commit:
```
git add Dev/kb_chatbot/ticket_ingest.py Dev/kb_chatbot/ingest.py Dev/kb_chatbot/config.py Dev/kb_chatbot/tests/test_ticket_ingest.py
git commit -m "feat(v2.6): ingest tickets as redacted problem+resolution chunks"
```

---

## Task 6: Ticket citation + prompt (§3c)

**Files:** Modify `prompt.py`; Test `tests/test_citations.py`, `tests/test_prompt.py`

- [ ] **Step 1: Write failing tests.** Append to `tests/test_citations.py`:
```python
def test_ticket_citation_validates_against_resolution_url():
    from Dev.kb_chatbot.citations import validate
    from Dev.kb_chatbot.chunker import Chunk
    url = "https://support.contoso.example/Resolution.aspx?bugid=75100"
    chunk = Chunk(id="ticket_x", text="…", metadata={"kind": "ticket", "ticket_id": "75100",
                  "title": "Ticket #75100", "url": url, "product": "tradedesk"})
    answer = f"Restart the FixApp session. [Ticket #75100 · TradeDesk]({url})"
    res = validate(answer, [chunk])
    assert len(res.verified) == 1
    assert "[unverified]" not in res.stripped_text
```
Append to `tests/test_prompt.py`:
```python
def test_ticket_context_label_and_rule():
    from Dev.kb_chatbot.prompt import _cite_handle, build_system_prompt
    h = _cite_handle({"kind": "ticket", "ticket_id": "75100", "product": "tradedesk",
                      "url": "https://support.contoso.example/Resolution.aspx?bugid=75100"})
    assert h.startswith("[Ticket #75100 · TradeDesk]")
    assert "ticket" in build_system_prompt().lower()
```

- [ ] **Step 2: Run — expect failures** (no ticket branch in `_cite_handle`; no ticket rule in prompt). The citations test already passes (URL match is generic) — keep it as a regression guard.

- [ ] **Step 3: Implement in `prompt.py`.** Update `_cite_handle` to branch on ticket:
```python
def _cite_handle(meta: dict) -> str:
    url = meta.get("url", "")
    if meta.get("kind") == "ticket":
        product = config.PRODUCT_DISPLAY.get(meta.get("product", ""), meta.get("product", ""))
        label = f"Ticket #{meta.get('ticket_id','')} · {product}"
        return f"[{label}]({url})" if url else f"[{label}]"
    product = config.PRODUCT_DISPLAY.get(meta.get("product", ""), meta.get("product", ""))
    category = meta.get("category", "") or "general"
    title = meta.get("title", "")
    if url:
        return f"[{product} · {category} · {title}]({url})"
    return f"[{product} · {category} · {title}]"
```
Add a ticket rule to `SYSTEM_PROMPT` (insert as rule 8, before the closing paragraph):
```
8. CONTEXT may include past support tickets (labelled "Ticket #<id>"). If a ticket resolved a similar issue, you may present its resolution and cite it as [Ticket #<id>](url) using the exact URL from CONTEXT. Never include customer names, emails, phone numbers, or company names — they are not in CONTEXT and must never be invented.
```

- [ ] **Step 4: Run** `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_citations.py Dev/kb_chatbot/tests/test_prompt.py -v` → pass.

- [ ] **Step 5: Commit**
```
git add Dev/kb_chatbot/prompt.py Dev/kb_chatbot/tests/test_citations.py Dev/kb_chatbot/tests/test_prompt.py
git commit -m "feat(v2.6): ticket citation label + prompt rule (no-PII)"
```

---

## Task 7: Packaging — one-folder, offline models, real Claude CLI (§4)

**Files:** Modify `ContosoKBChatbot.spec`, `gui.py`, `llm/claude_code_provider.py`, `build_chatbot_exe.bat`. No unit tests (build/runtime); verified live in Task 8.

- [ ] **Step 1: HF offline env BEFORE model imports.** At the very top of `Dev/kb_chatbot/gui.py`, immediately after `import sys` / `import os` (add `import os` if absent) and BEFORE any `from Dev.kb_chatbot...` import that pulls sentence-transformers, add:
```python
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# When frozen, point HF at the model cache shipped inside the app folder.
if getattr(sys, "frozen", False):
    _models = os.path.join(os.path.dirname(sys.executable), "models")
    if os.path.isdir(_models):
        os.environ.setdefault("HF_HOME", _models)
```
(Place after `import sys`. This must run before `retriever`/`ingest` import sentence-transformers.)

- [ ] **Step 2: Real Claude CLI in `claude_code_provider.py`.** In `_ensure_client` where `ClaudeAgentOptions(system_prompt=system_prompt, model=model)` is built, pass the resolved CLI path:
```python
        import shutil as _shutil
        cli = _shutil.which("claude")
        opts_kwargs = {"system_prompt": system_prompt, "model": model}
        if cli:
            opts_kwargs["cli_path"] = cli
        options = ClaudeAgentOptions(**opts_kwargs)
```
(Guarded so it still works if `cli_path` isn't supported / claude not found — falls back to SDK default.)

- [ ] **Step 3: One-folder spec + bundle models + exclude `_bundled`.** Edit `ContosoKBChatbot.spec`:

(a) After the `collect_all` loop, drop the SDK's bundled CLI from datas/binaries:
```python
datas = [(s, d) for (s, d) in datas if "_bundled" not in s.replace("\\", "/")]
binaries = [(s, d) for (s, d) in binaries if "_bundled" not in s.replace("\\", "/")]
```

(b) Bundle the HF model caches into a `models/` folder in the build. Add before `Analysis(...)`:
```python
import os as _os
_hf = _os.path.join(_os.path.expanduser("~"), ".cache", "huggingface")
if _os.path.isdir(_hf):
    for _root, _dirs, _files in _os.walk(_hf):
        for _f in _files:
            _full = _os.path.join(_root, _f)
            _rel = _os.path.relpath(_full, _hf)
            datas.append((_full, _os.path.join("models", _os.path.dirname(_rel))))
```
(So the cache ships under `dist/ContosoKBChatbot/models/…` and Step 1's `HF_HOME` points there.)

(c) Convert from one-file to one-folder: change the `EXE(...)` call to exclude the heavy collections, and add a `COLLECT(...)`:
```python
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ContosoKBChatbot",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="ContosoKBChatbot",
)
```

- [ ] **Step 4: InitWorker stage text in `gui.py`.** In `InitWorker.run`, set the two status emits to the clearer wording:
```python
            self.status.emit("✦ Loading search models…")
```
(before building the Retriever) and keep the existing warm-up emit, but reword to:
```python
            self.status.emit(f"✦ Warming up {display}…")
```
(The window already shows instantly via Task-7 onedir; `_on_init_status` pins these.)

- [ ] **Step 5: `build_chatbot_exe.bat`** — update the echo to note the output is now a folder: change the success message to `echo Build complete. Artifact: dist\ContosoKBChatbot\ContosoKBChatbot.exe (distribute the whole ContosoKBChatbot folder).`

- [ ] **Step 6: Verify imports unaffected**
```
& "scraper\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0,'.'); from Dev.kb_chatbot import gui; print('import OK')"
& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/ -q
```
Both pass.

- [ ] **Step 7: Commit**
```
git add Dev/kb_chatbot/gui.py Dev/kb_chatbot/llm/claude_code_provider.py ContosoKBChatbot.spec build_chatbot_exe.bat
git commit -m "build(v2.6): one-folder build, offline bundled models, drop bundled-claude, real CLI path"
```

---

## Task 8: Final integration — live verify, §1b fix, docs, build

- [ ] **Step 1: Full suite**
```
& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/ -q
```
Expected: all pass.

- [ ] **Step 2: Live Codex smoke + §1b frozen-cause fix.** Run a real Codex call through the provider:
```
& "scraper\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0,'.'); from Dev.kb_chatbot.llm.codex_provider import CodexProvider; r=CodexProvider().chat(messages=[{'role':'user','content':'Reply with exactly: pong'}], model='gpt-5.4-mini', system_prompt='You are a test.'); print(repr(r.text), r.input_tokens, r.output_tokens)"
```
Expected: prints `'pong'` with token counts. If it now raises `CodexExecError`, read the message/`run.log` stderr — that is the real frozen-cause evidence. Apply the precise fix it indicates (the `-C` safe-cwd from Task 1 is the first candidate; if stderr shows a different cause, fix that), add a regression test, and re-run. Commit any §1b fix:
```
git commit -am "fix(v2.6): codex frozen-exec cause (<from captured stderr>)"
```

- [ ] **Step 3: Live accuracy check.** Reindex a temp DB including tickets and confirm a previously-abstaining query now answers and that a ticket surfaces:
```
& "scraper\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0,'.'); from pathlib import Path; import tempfile; from Dev.kb_chatbot.ingest import ingest; d=tempfile.mkdtemp(); rep=ingest(Path('library/kb'), Path(d), tickets_path=Path('library/tickets')); print('articles', rep.articles_seen, 'chunks', rep.chunks_created, 'products', rep.products)"
```
Expected: `products` includes a `tickets` count > 0; chunks created. (Full retrieval-quality is validated in the manual walkthrough.)

- [ ] **Step 4: Version + docs + buglog.** Bump version strings to v2.6 (module docstrings touched). Update `docs` is already committed. Append to `.wolf/buglog.json` entries for: codex-blank-on-failure, logit-floor miscalibration, onefile-unpack slowness, 234MB bundled-claude bloat (each with root_cause + fix). Update memory: `MEMORY.md` pointer line + `project_kb_chatbot_v23.md` v2.6 summary.
```
git add -A && git commit -m "docs(v2.6): buglog + memory + version bump"
```

- [ ] **Step 5: Build the one-folder exe** (background) and verify instant launch + offline:
```
& "scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBChatbot.spec --clean --noconfirm
```
Then confirm `dist\ContosoKBChatbot\ContosoKBChatbot.exe` exists and the `models\` folder is present beside it.

- [ ] **Step 6: Manual walkthrough checklist (user):**
  1. Launch the folder's exe → window appears in ~1s; status shows `✦ Loading search models…` → `✦ Warming up …` → Ready (no internet needed).
  2. ChatGPT provider → ask a KB question → real answer (no blank); if Codex fails you now see a clear error, not silence.
  3. Ask something that previously said "not in KB" → now answers (recalibrated floor).
  4. Ask about an issue covered by a ticket (e.g. CAB pricing / FixApp) → answer references `[Ticket #…]` with the resolution link, **no customer names/emails**.
  5. Claude provider → still answers.
  6. Token viewer → ticket/Claude/ChatGPT rows render.

- [ ] **Step 7:** Do NOT merge — `finishing-a-development-branch` handles merge after walkthrough.
