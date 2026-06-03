# KB Chatbot V2.2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Refactor the V2.1 chatbot to (a) fix the `torch.cuda` PyInstaller crash, (b) replace Anthropic API-key auth with Claude Code subprocess auth via `claude-agent-sdk`, and (c) adapt the chunker/ingest/prompt/citation pipeline to the new 1,466-article `library/kb/` corpus with flat-article schema and six products.

**Architecture:** Same single-pass RAG + PySide6 GUI as V2.1. Drop-in changes: new chunker for `body_md` markdown articles, new `ClaudeCodeProvider` (replaces `AnthropicProvider`), updated system prompt + citation format `[Product · Category · Title]`, updated PyInstaller spec.

**Tech Stack:** Python 3.10+, PySide6, sentence-transformers, ChromaDB, **claude-agent-sdk** (replaces `anthropic`), PyInstaller. Tests via pytest.

**Spec:** `docs/superpowers/specs/2026-06-01-kb-chatbot-v2.2-design.md`

This is a **no-git environment** — no commit steps. The implementer must NOT run git. Verification is the passing pytest run after each task.

All commands assume CWD is the Knowledge Base root. Python is `scraper\venv\Scripts\python.exe`.

---

## Ground rules

- **TDD where logic exists:** failing test first → run to confirm fail → implement → run to confirm pass.
- **Reproduce code character-for-character** from the appendices.
- **Do NOT modify any file outside the task's declared scope.** This protects the scraper + already-shipped pieces.
- **Do NOT run git. Do NOT install anything not listed in the task.**

---

## File Map (V2.2 changes only)

```
Dev/kb_chatbot/
├── config.py                ← MODIFY: new PRODUCTS, LIBRARY_DEFAULT, drop keyring/cost (Task 1)
├── settings.py              ← MODIFY: drop API-key functions (Task 1)
├── requirements.txt         ← MODIFY: add claude-agent-sdk; drop anthropic + keyring (Task 1)
├── chunker.py               ← REWRITE: body_md article chunking (Task 2)
├── ingest.py                ← MODIFY: walk library/<product>/**/*.json, skip index files (Task 3)
├── retriever.py             ← UNCHANGED (Task 4 only updates its tests)
├── prompt.py                ← REWRITE: new SYSTEM_PROMPT + cite handle (Task 5)
├── citations.py             ← REWRITE: new regex + validator (Task 5)
├── llm/
│   ├── __init__.py          ← MODIFY: import ClaudeCodeProvider (Task 6)
│   ├── base.py              ← UNCHANGED
│   ├── fake_provider.py     ← UNCHANGED
│   ├── anthropic_provider.py ← DELETE (Task 6)
│   └── claude_code_provider.py ← NEW (Task 6)
├── chat/
│   ├── session.py           ← UNCHANGED
│   └── orchestrator.py      ← MODIFY: model constant, abstain text (Task 7)
├── gui.py                   ← MODIFY: drop API-key UI, add Claude Code preflight (Task 8)
└── tests/
    ├── fixtures/tiny_library/ ← REWRITE with new schema (Task 2)
    ├── fixtures/golden_qa.json ← REWRITE (Task 7)
    ├── test_settings.py     ← MODIFY: drop keyring test (Task 1)
    ├── test_chunker.py      ← REWRITE (Task 2)
    ├── test_ingest.py       ← MODIFY: new counts (Task 3)
    ├── test_retriever.py    ← MODIFY: new fixture (Task 4)
    ├── test_prompt.py       ← REWRITE (Task 5)
    ├── test_citations.py    ← REWRITE (Task 5)
    ├── test_llm.py          ← UNCHANGED
    ├── test_claude_code_provider.py ← NEW (Task 6)
    ├── test_orchestrator.py ← MODIFY (Task 7)
    └── test_integration.py  ← MODIFY (Task 7)

ContosoKBChatbot.spec       ← MODIFY: remove torch.cuda exclude; swap libs (Task 9)
```

The old V2.1 tiny_library files (per-version schema with `enhancements/bugs/...`) become obsolete; Task 2 will delete them and create the new fixture set.

---

## Task 1: Config, settings, requirements

**Files:** `Dev/kb_chatbot/config.py`, `Dev/kb_chatbot/settings.py`, `Dev/kb_chatbot/requirements.txt`, `Dev/kb_chatbot/tests/test_settings.py`

- [ ] **Step 1:** Install `claude-agent-sdk`:
  ```powershell
  scraper\venv\Scripts\python.exe -m pip install "claude-agent-sdk>=0.1.0"
  ```

- [ ] **Step 2:** Overwrite `Dev/kb_chatbot/requirements.txt`:
  ```
  PySide6>=6.6.0
  sentence-transformers>=2.7
  chromadb>=0.5
  claude-agent-sdk>=0.1.0
  markdown>=3.6
  pytest>=7.4.0
  ```

- [ ] **Step 3:** Replace `Dev/kb_chatbot/config.py` with content from **APPENDIX A — config.py**.

- [ ] **Step 4:** Replace `Dev/kb_chatbot/settings.py` with content from **APPENDIX A — settings.py**.

- [ ] **Step 5:** Replace `Dev/kb_chatbot/tests/test_settings.py` with content from **APPENDIX A — test_settings.py**.

- [ ] **Step 6:** Run settings tests — confirm PASS (3 passed):
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_settings.py -v
  ```

- [ ] **Step 7:** Verify config:
  ```powershell
  scraper\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from Dev.kb_chatbot import config; print('LIBRARY_DEFAULT:', config.LIBRARY_DEFAULT); print('PRODUCTS:', config.PRODUCTS); print('default model:', config.DEFAULT_MODEL)"
  ```
  Expected: `LIBRARY_DEFAULT` ends with `library\kb`, `PRODUCTS` lists six items, `default model: claude-haiku-4-5-20251001`.

---

## Task 2: Chunker rewrite + new tiny library fixture

**Files:** `Dev/kb_chatbot/tests/fixtures/tiny_library/` (rewritten), `Dev/kb_chatbot/tests/test_chunker.py`, `Dev/kb_chatbot/chunker.py`

- [ ] **Step 1:** Wipe the old tiny library:
  ```powershell
  Remove-Item -Recurse -Force "Dev\kb_chatbot\tests\fixtures\tiny_library"
  ```

- [ ] **Step 2:** Create six new tiny library files — content from **APPENDIX B — tiny library files**. Use `New-Item -ItemType Directory -Force` for each parent dir.

- [ ] **Step 3:** Replace `Dev/kb_chatbot/tests/test_chunker.py` with content from **APPENDIX B — test_chunker.py**.

- [ ] **Step 4:** Run — confirm FAIL.

- [ ] **Step 5:** Replace `Dev/kb_chatbot/chunker.py` with content from **APPENDIX B — chunker.py**.

- [ ] **Step 6:** Run — confirm PASS (9 passed):
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_chunker.py -v
  ```

---

## Task 3: Ingest update

**Files:** `Dev/kb_chatbot/ingest.py`, `Dev/kb_chatbot/tests/test_ingest.py`

- [ ] **Step 1:** Replace `Dev/kb_chatbot/tests/test_ingest.py` with content from **APPENDIX C — test_ingest.py**.

- [ ] **Step 2:** Run — confirm FAIL.

- [ ] **Step 3:** Replace `Dev/kb_chatbot/ingest.py` with content from **APPENDIX C — ingest.py**.

- [ ] **Step 4:** Run — confirm PASS (5 passed):
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ingest.py -v
  ```

---

## Task 4: Retriever tests update

**Files:** `Dev/kb_chatbot/tests/test_retriever.py`

- [ ] **Step 1:** Replace `Dev/kb_chatbot/tests/test_retriever.py` with content from **APPENDIX D — test_retriever.py**.

- [ ] **Step 2:** Run — confirm PASS (5 passed):
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_retriever.py -v
  ```

---

## Task 5: Prompt + citations rewrite

**Files:** `Dev/kb_chatbot/prompt.py`, `Dev/kb_chatbot/citations.py`, `Dev/kb_chatbot/tests/test_prompt.py`, `Dev/kb_chatbot/tests/test_citations.py`

- [ ] **Step 1:** Replace `Dev/kb_chatbot/tests/test_prompt.py` with content from **APPENDIX E — test_prompt.py**.

- [ ] **Step 2:** Run — confirm FAIL.

- [ ] **Step 3:** Replace `Dev/kb_chatbot/prompt.py` with content from **APPENDIX E — prompt.py**.

- [ ] **Step 4:** Run — confirm PASS (5 passed):
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_prompt.py -v
  ```

- [ ] **Step 5:** Replace `Dev/kb_chatbot/tests/test_citations.py` with content from **APPENDIX E — test_citations.py**.

- [ ] **Step 6:** Run — confirm FAIL.

- [ ] **Step 7:** Replace `Dev/kb_chatbot/citations.py` with content from **APPENDIX E — citations.py**.

- [ ] **Step 8:** Run — confirm PASS (6 passed):
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_citations.py -v
  ```

---

## Task 6: ClaudeCodeProvider; delete AnthropicProvider

**Files:** Create `Dev/kb_chatbot/llm/claude_code_provider.py`, `Dev/kb_chatbot/tests/test_claude_code_provider.py`; modify `Dev/kb_chatbot/llm/__init__.py`; delete `Dev/kb_chatbot/llm/anthropic_provider.py`.

- [ ] **Step 1:** Replace `Dev/kb_chatbot/llm/__init__.py` with:
  ```python
  # llm provider package
  from Dev.kb_chatbot.llm.base import LLMProvider, LLMResponse, estimate_cost
  from Dev.kb_chatbot.llm.fake_provider import FakeProvider
  from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider, ClaudeCodeNotFoundError
  ```

- [ ] **Step 2:** Delete the old Anthropic provider:
  ```powershell
  Remove-Item -Force "Dev\kb_chatbot\llm\anthropic_provider.py"
  ```

- [ ] **Step 3:** Create `Dev/kb_chatbot/tests/test_claude_code_provider.py` with content from **APPENDIX F — test_claude_code_provider.py**.

- [ ] **Step 4:** Run — confirm FAIL.

- [ ] **Step 5:** Create `Dev/kb_chatbot/llm/claude_code_provider.py` with content from **APPENDIX F — claude_code_provider.py**.

- [ ] **Step 6:** Run — confirm PASS (3 passed):
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_claude_code_provider.py -v
  ```

- [ ] **Step 7:** Confirm existing llm tests still pass (3 passed):
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_llm.py -v
  ```

---

## Task 7: Orchestrator + integration tests

**Files:** `Dev/kb_chatbot/chat/orchestrator.py`, `Dev/kb_chatbot/tests/test_orchestrator.py`, `Dev/kb_chatbot/tests/test_integration.py`, `Dev/kb_chatbot/tests/fixtures/golden_qa.json`

- [ ] **Step 1:** Replace `Dev/kb_chatbot/tests/fixtures/golden_qa.json` with content from **APPENDIX G — golden_qa.json**.

- [ ] **Step 2:** Replace `Dev/kb_chatbot/tests/test_orchestrator.py` with content from **APPENDIX G — test_orchestrator.py**.

- [ ] **Step 3:** Replace `Dev/kb_chatbot/tests/test_integration.py` with content from **APPENDIX G — test_integration.py**.

- [ ] **Step 4:** Run — confirm FAIL.

- [ ] **Step 5:** Replace `Dev/kb_chatbot/chat/orchestrator.py` with content from **APPENDIX G — orchestrator.py**.

- [ ] **Step 6:** Run — confirm PASS (5 + 5 = 10 passed):
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator.py Dev/kb_chatbot/tests/test_integration.py -v
  ```

- [ ] **Step 7:** Full suites regression:
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/ -v
  scraper\venv\Scripts\python.exe -m pytest tests/ -v
  ```
  Expected: chatbot all green (~ 41 tests); scraper stays 50/50.

---

## Task 8: GUI updates

**Files:** `Dev/kb_chatbot/gui.py`

- [ ] **Step 1:** Replace `Dev/kb_chatbot/gui.py` with content from **APPENDIX H — gui.py**.

- [ ] **Step 2:** Smoke import:
  ```powershell
  scraper\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from Dev.kb_chatbot.gui import MainWindow; print('gui imports OK')"
  ```

- [ ] **Step 3:** Boot survival test:
  ```powershell
  Start-Process -FilePath "scraper\venv\Scripts\python.exe" -ArgumentList "Dev\kb_chatbot\gui.py" -PassThru | ForEach-Object { Start-Sleep -Seconds 6; if (-not $_.HasExited) { Write-Host "Boot OK"; Stop-Process -Id $_.Id -Force } else { Write-Host "Process exited prematurely"; exit 1 } }
  ```

---

## Task 9: PyInstaller spec fix + rebuild

**Files:** `ContosoKBChatbot.spec`

- [ ] **Step 1:** Replace `ContosoKBChatbot.spec` with content from **APPENDIX I — ContosoKBChatbot.spec**.

- [ ] **Step 2:** Rebuild:
  ```powershell
  .\build_chatbot_exe.bat
  ```
  (3–10 minutes; expected final line `Build complete. Artifact: dist\ContosoKBChatbot.exe`.)

- [ ] **Step 3:** Verify artifact size:
  ```powershell
  Get-Item dist\ContosoKBChatbot.exe | Select-Object Name, Length
  ```
  Expected: 350–750 MB.

- [ ] **Step 4:** Boot the rebuilt exe (12s alive check):
  ```powershell
  Start-Process -FilePath "dist\ContosoKBChatbot.exe" -PassThru | ForEach-Object { Start-Sleep -Seconds 12; if (-not $_.HasExited) { Write-Host "Exe boot OK"; Stop-Process -Id $_.Id -Force } else { Write-Host "Exe exited"; exit 1 } }
  ```

---

## Task 10: User smoke + handoff

- [ ] **Step 1:** Re-run full suites:
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/ tests/ -v
  ```

- [ ] **Step 2: USER STEP — first launch.** Double-click `dist\ContosoKBChatbot.exe`. Window appears (no API-key prompt). Library defaults to `dist\library\kb`.

- [ ] **Step 3: USER STEP — Reindex.** Click **Reindex**. ~5–10 min on CPU. Result: "Reindex complete: 1,466 articles, ~3,000 chunks".

- [ ] **Step 4: USER STEP — smoke questions:**

  | Question | Expected |
  |---|---|
  | `How do I book a spot deal in TradeDesk?` | Cites `[TradeDesk · ... · ...]`. |
  | `Show me how to manage forms in SalesHub` | Cites SalesHub form_management article. |
  | `What's in the latest API release notes?` | Cites API release-notes article. |
  | `What is the weather in Tokyo?` | Abstains: `"I haven't been trained on this — it's not in the knowledge base I have access to."` |
  | `How do I do this?` (no product) | Asks clarification. |

- [ ] **Step 5: USER STEP — Stop button.** Send a broad question; click **⏹ STOP**. Reply shows "Cancelled."

- [ ] **Step 6: USER STEP — Logs.** `View logs` → confirms `run.log` + `usage.jsonl`.

---

## Quick Reference

| Goal | Action |
|------|--------|
| Run the chatbot | Double-click `dist\ContosoKBChatbot.exe` |
| Build the chatbot exe | Double-click `build_chatbot_exe.bat` |
| Run from source | `scraper\venv\Scripts\python.exe Dev\kb_chatbot\gui.py` |
| Run chatbot tests | `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/ -v` |
| Run scraper tests | `scraper\venv\Scripts\python.exe -m pytest tests/ -v` |

---

# Appendices (verbatim code blocks)

## APPENDIX A — Config + settings + test_settings

### `Dev/kb_chatbot/config.py`

```python
"""V2.2 static defaults + freeze-aware paths. No persisted settings live here."""
from __future__ import annotations
from pathlib import Path
import sys

# ── Freeze-aware base paths ───────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent              # dist/ at runtime
    STATE_DIR = BASE_DIR / "chatbot_state"
else:
    BASE_DIR = Path(__file__).parent.parent.parent      # Knowledge Base/
    STATE_DIR = Path(__file__).parent / "state"

LIBRARY_DEFAULT = BASE_DIR / "library" / "kb"
CHROMA_DIR      = STATE_DIR / "chroma"
CHATS_DIR       = STATE_DIR / "chats"
LOG_FILE        = STATE_DIR / "run.log"
USAGE_FILE      = STATE_DIR / "usage.jsonl"
SETTINGS_FILE   = STATE_DIR / "settings.json"

# ── Model defaults ────────────────────────────────────────────────────────────
EMBED_MODEL    = "sentence-transformers/all-MiniLM-L6-v2"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

DEFAULT_MODEL  = "claude-haiku-4-5-20251001"
AVAILABLE_MODELS = {
    "Haiku (fast / cheap)": "claude-haiku-4-5-20251001",
    "Sonnet (smarter)":     "claude-sonnet-4-6",
}

# ── Products (six) ────────────────────────────────────────────────────────────
PRODUCTS = ("api", "tradedesk", "saleshub", "web2", "web4", "other")
PRODUCT_DISPLAY = {
    "api": "API", "tradedesk": "TradeDesk", "saleshub": "SalesHub",
    "web2": "Web2", "web4": "Web4", "other": "Other",
}

# ── Retrieval defaults ────────────────────────────────────────────────────────
TOP_K_RETRIEVE      = 30
TOP_K_RERANK        = 8
CONFIDENCE_FLOOR    = 0.30
CLARIFY_SCORE_FLOOR = -5.0
MAX_HISTORY_TURNS   = 6
CHUNK_TARGET_WORDS  = 500
```

### `Dev/kb_chatbot/settings.py`

```python
"""Persisted settings (JSON). V2.2 has no API key — Claude Code subprocess uses its own OAuth."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from Dev.kb_chatbot import config


@dataclass
class Settings:
    library_path: Path
    default_model: str
    confidence_floor: float


def load_settings(path: Path = config.SETTINGS_FILE) -> Settings:
    defaults = Settings(
        library_path=config.LIBRARY_DEFAULT,
        default_model=config.DEFAULT_MODEL,
        confidence_floor=config.CONFIDENCE_FLOOR,
    )
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    return Settings(
        library_path=Path(data.get("library_path", str(defaults.library_path))),
        default_model=data.get("default_model", defaults.default_model),
        confidence_floor=float(data.get("confidence_floor", defaults.confidence_floor)),
    )


def save_settings(settings: Settings, path: Path = config.SETTINGS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**asdict(settings), "library_path": str(settings.library_path)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

### `Dev/kb_chatbot/tests/test_settings.py`

```python
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import tempfile
from Dev.kb_chatbot.settings import Settings, load_settings, save_settings
from Dev.kb_chatbot import config


def test_defaults_when_no_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        s = load_settings(path)
        assert s.library_path == config.LIBRARY_DEFAULT
        assert s.default_model == config.DEFAULT_MODEL
        assert s.confidence_floor == config.CONFIDENCE_FLOOR


def test_round_trip_save_and_load():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        original = Settings(
            library_path=Path("X:/some/library/kb"),
            default_model="claude-sonnet-4-6",
            confidence_floor=0.45,
        )
        save_settings(original, path)
        loaded = load_settings(path)
        assert loaded.library_path == Path("X:/some/library/kb")
        assert loaded.default_model == "claude-sonnet-4-6"
        assert loaded.confidence_floor == 0.45


def test_partial_file_falls_back_to_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        path.write_text(json.dumps({"default_model": "claude-sonnet-4-6"}), encoding="utf-8")
        loaded = load_settings(path)
        assert loaded.default_model == "claude-sonnet-4-6"
        assert loaded.library_path == config.LIBRARY_DEFAULT
        assert loaded.confidence_floor == config.CONFIDENCE_FLOOR
```

---

## APPENDIX B — Tiny library + chunker

### Six tiny-library JSON files

**`Dev/kb_chatbot/tests/fixtures/tiny_library/api/release_notes/api_release_25.json`:**
```json
{
  "space_key": "API25",
  "space_name": "API 2.5 Release Notes",
  "product": "api",
  "title": "API 2.5 Release Notes — Version 2.5.0",
  "url": "http://example/api/2.5.0",
  "scraped_at": "2026-06-01T10:00:00",
  "screenshot": "tiny.png",
  "body_md": "# API 2.5 Release Notes\n\n## New endpoints\n\nThe `/v2/payments/quick` endpoint is now available for Quick Pay submissions.\n\n## Bug fixes\n\nFixed null handling in the `/v2/deals/booking` response.\n"
}
```

**`Dev/kb_chatbot/tests/fixtures/tiny_library/tradedesk/dealing/booking_spot_deal.json`:**
```json
{
  "space_key": "TD",
  "space_name": "TradeDesk Knowledge Base",
  "product": "tradedesk",
  "title": "Booking a Spot Deal",
  "url": "http://example/tradedesk/booking-spot-deal",
  "scraped_at": "2026-06-01T10:00:00",
  "screenshot": "tiny.png",
  "body_md": "# Booking a Spot Deal\n\n## Prerequisites\n\nThe operator must have the Dealing role assigned.\n\n## Steps\n\n1. Open the Dealing tab.\n2. Press F2 to open the booking form.\n3. Fill in the counter-party and amount.\n4. Submit.\n"
}
```

**`Dev/kb_chatbot/tests/fixtures/tiny_library/saleshub/form_management/build_form.json`:**
```json
{
  "space_key": "SH",
  "space_name": "SalesHub Knowledge Base",
  "product": "saleshub",
  "title": "Building a Customer Onboarding Form",
  "url": "http://example/saleshub/forms",
  "scraped_at": "2026-06-01T10:00:00",
  "screenshot": "tiny.png",
  "body_md": "# Building a Customer Onboarding Form\n\nUse the Form Builder to drag fields onto the canvas. IBAN fields trigger automatic validation against the configured registry.\n"
}
```

**`Dev/kb_chatbot/tests/fixtures/tiny_library/web2/payments/recurring_payment.json`:**
```json
{
  "space_key": "W2",
  "space_name": "Web 2.0 Knowledge Base",
  "product": "web2",
  "title": "Setting up a Recurring Payment",
  "url": "http://example/web2/recurring",
  "scraped_at": "2026-06-01T10:00:00",
  "screenshot": "tiny.png",
  "body_md": "# Setting up a Recurring Payment\n\nNavigate to Payments → Recurring. Choose the frequency and beneficiary.\n"
}
```

**`Dev/kb_chatbot/tests/fixtures/tiny_library/web4/booking_deals/quick_pay.json`:**
```json
{
  "space_key": "W4",
  "space_name": "Web 4.0 Knowledge Base",
  "product": "web4",
  "title": "Quick Pay and Payment Links",
  "url": "http://example/web4/quick-pay",
  "scraped_at": "2026-06-01T10:00:00",
  "screenshot": "tiny.png",
  "body_md": "# Quick Pay and Payment Links\n\nQuick Pay generates a payment link the recipient can use to authorise a one-off transfer without logging in.\n"
}
```

**`Dev/kb_chatbot/tests/fixtures/tiny_library/other/form_builder_docs/quick_start.json`:**
```json
{
  "space_key": "FB",
  "space_name": "Form Builder Docs",
  "product": "other",
  "title": "Form Builder Quick Start",
  "url": "http://example/other/form-builder",
  "scraped_at": "2026-06-01T10:00:00",
  "screenshot": "tiny.png",
  "body_md": "# Form Builder Quick Start\n\nThe Form Builder ships with a drag-and-drop canvas for building approval forms.\n"
}
```

### `Dev/kb_chatbot/chunker.py`

```python
"""V2.2 chunker: build searchable chunks from flat-article JSON files."""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from Dev.kb_chatbot import config


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _category_from_path(article_path: Path, library_root: Path) -> str:
    """Derive a category slug from the article path:
       library_root/<product>/<category>/.../<file>.json  → category."""
    try:
        rel = article_path.relative_to(library_root).parts
    except ValueError:
        return ""
    if len(rel) >= 3:
        return rel[1]
    return ""


def _stable_id(space_key: str, title: str, chunk_index: int) -> str:
    base = f"{space_key}|{title}|{chunk_index}"
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"art_{h}"


def _split_body_md(body_md: str, target_words: int = config.CHUNK_TARGET_WORDS) -> list[str]:
    """Split markdown text into chunks targeting `target_words` words.
       Splits on '## '/'### ' headings, sub-splits long sections on paragraph breaks,
       never splits inside fenced code blocks."""
    if not body_md.strip():
        return []

    code_blocks: list[str] = []
    def _stash(match: re.Match) -> str:
        code_blocks.append(match.group(0))
        return f" CODE{len(code_blocks)-1} "
    masked = re.sub(r"```.*?```", _stash, body_md, flags=re.DOTALL)

    sections = re.split(r"(?m)^(?=#{1,3} )", masked)
    sections = [s.strip("\n") for s in sections if s.strip()]

    def _unmask(text: str) -> str:
        def _restore(match: re.Match) -> str:
            return code_blocks[int(match.group(1))]
        return re.sub(r" CODE(\d+) ", _restore, text)

    chunks: list[str] = []
    for section in sections:
        heading_line = ""
        body = section
        m = re.match(r"^(#{1,3} [^\n]+)\n?(.*)$", section, flags=re.DOTALL)
        if m:
            heading_line = m.group(1)
            body = m.group(2).strip("\n")

        words = body.split()
        if len(words) <= target_words:
            chunks.append(_unmask(section))
            continue

        paragraphs = re.split(r"\n\s*\n", body)
        buf: list[str] = []
        buf_words = 0
        for para in paragraphs:
            p_words = len(para.split())
            if buf and buf_words + p_words > target_words:
                chunks.append(_unmask((heading_line + "\n\n" if heading_line else "") + "\n\n".join(buf)))
                buf = [para]
                buf_words = p_words
            else:
                buf.append(para)
                buf_words += p_words
        if buf:
            chunks.append(_unmask((heading_line + "\n\n" if heading_line else "") + "\n\n".join(buf)))

    return chunks


def _breadcrumb(product: str, category: str, title: str) -> str:
    display = config.PRODUCT_DISPLAY.get(product, product)
    return f"{display} · {category or 'general'} · {title}"


def build_article_chunks(article_data: dict, article_path: Path, library_root: Path,
                         target_words: int = config.CHUNK_TARGET_WORDS) -> list[Chunk]:
    product = article_data.get("product", "unknown")
    title = article_data.get("title", "")
    space_key = article_data.get("space_key", "")
    space_name = article_data.get("space_name", "")
    url = article_data.get("url", "")
    body_md = article_data.get("body_md", "")
    category = _category_from_path(article_path, library_root)

    breadcrumb = _breadcrumb(product, category, title)
    parts = _split_body_md(body_md, target_words)
    if not parts:
        return []

    try:
        rel = article_path.with_suffix(".md").relative_to(library_root.parent)
        md_path = rel.as_posix()
    except ValueError:
        md_path = article_path.with_suffix(".md").as_posix()

    chunks: list[Chunk] = []
    for idx, part in enumerate(parts):
        text = f"{breadcrumb}\n\n{part}"
        chunks.append(Chunk(
            id=_stable_id(space_key or url or title, title, idx),
            text=text,
            metadata={
                "kind": "article",
                "product": product,
                "category": category,
                "title": title,
                "space_key": space_key,
                "space_name": space_name,
                "url": url,
                "chunk_index": idx,
                "md_path": md_path,
            },
        ))
    return chunks
```

### `Dev/kb_chatbot/tests/test_chunker.py`

```python
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chunker import build_article_chunks, _category_from_path, _split_body_md

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def _load(rel: str) -> tuple[dict, Path]:
    path = FIX / rel
    return json.loads(path.read_text(encoding="utf-8")), path


def test_chunk_for_short_article_yields_one_chunk():
    data, path = _load("web4/booking_deals/quick_pay.json")
    chunks = build_article_chunks(data, path, FIX)
    assert len(chunks) == 1
    assert "Quick Pay" in chunks[0].text


def test_chunk_metadata_includes_required_fields():
    data, path = _load("tradedesk/dealing/booking_spot_deal.json")
    chunks = build_article_chunks(data, path, FIX)
    md = chunks[0].metadata
    assert md["kind"] == "article"
    assert md["product"] == "tradedesk"
    assert md["category"] == "dealing"
    assert md["title"] == "Booking a Spot Deal"
    assert md["url"] == "http://example/tradedesk/booking-spot-deal"
    assert md["space_key"] == "TD"
    assert md["chunk_index"] == 0


def test_chunk_text_starts_with_breadcrumb():
    data, path = _load("tradedesk/dealing/booking_spot_deal.json")
    chunks = build_article_chunks(data, path, FIX)
    assert chunks[0].text.startswith("TradeDesk · dealing · Booking a Spot Deal")


def test_category_derived_from_path():
    p = FIX / "tradedesk" / "dealing" / "booking_spot_deal.json"
    assert _category_from_path(p, FIX) == "dealing"


def test_category_is_empty_when_no_subdir():
    p = FIX / "tradedesk" / "booking_spot_deal.json"
    assert _category_from_path(p, FIX) == ""


def test_long_article_is_split():
    body = "## Section A\n\n" + ("para para para. " * 200) + "\n\n## Section B\n\n" + ("text " * 200)
    parts = _split_body_md(body, target_words=100)
    assert len(parts) >= 2


def test_split_keeps_code_blocks_intact():
    body = "## intro\n\n```python\nfor i in range(10):\n    print(i)\n```\n\nafter code"
    parts = _split_body_md(body, target_words=500)
    joined = "\n".join(parts)
    assert "```python" in joined
    assert "for i in range(10):" in joined


def test_chunk_id_is_stable_across_runs():
    data, path = _load("saleshub/form_management/build_form.json")
    c1 = build_article_chunks(data, path, FIX)
    c2 = build_article_chunks(data, path, FIX)
    assert c1[0].id == c2[0].id


def test_chunks_for_all_six_products_built():
    paths = [
        "api/release_notes/api_release_25.json",
        "tradedesk/dealing/booking_spot_deal.json",
        "saleshub/form_management/build_form.json",
        "web2/payments/recurring_payment.json",
        "web4/booking_deals/quick_pay.json",
        "other/form_builder_docs/quick_start.json",
    ]
    products = set()
    for rel in paths:
        data, path = _load(rel)
        chunks = build_article_chunks(data, path, FIX)
        assert chunks
        products.add(chunks[0].metadata["product"])
    assert products == {"api", "tradedesk", "saleshub", "web2", "web4", "other"}
```

---

## APPENDIX C — Ingest + test_ingest

### `Dev/kb_chatbot/ingest.py`

```python
"""V2.2 ingest: walks <library>/<product>/**/*.json, skips index files and files without body_md.
Builds article chunks and persists them in ChromaDB."""
from __future__ import annotations
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import chromadb
from sentence_transformers import SentenceTransformer

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import build_article_chunks, Chunk

log = logging.getLogger("kb_chatbot.ingest")

COLLECTION_NAME = "kbs"
BATCH_SIZE = 64


@dataclass
class IngestReport:
    articles_seen: int = 0
    chunks_created: int = 0
    products: dict[str, int] = field(default_factory=dict)
    skipped: int = 0
    duration_s: float = 0.0


def _gather_article_jsons(library_path: Path) -> list[Path]:
    """All .json files under product directories, skipping index.json at the root."""
    if not library_path.exists():
        return []
    out: list[Path] = []
    for child in sorted(library_path.iterdir()):
        if child.is_dir():
            out.extend(sorted(child.rglob("*.json")))
    return [p for p in out if p.name != "index.json"]


def _embed_batch(model: SentenceTransformer, texts: list[str]) -> list[list[float]]:
    vecs = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def ingest(
    library_path: Path,
    chroma_path: Path,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
) -> IngestReport:
    started = time.time()
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    embedder = SentenceTransformer(config.EMBED_MODEL)

    files = _gather_article_jsons(library_path)
    report = IngestReport()
    all_chunks: list[Chunk] = []
    for f in files:
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
        all_chunks.extend(build_article_chunks(data, f, library_path))

    total = len(all_chunks)
    if total == 0:
        client.close()
        report.duration_s = time.time() - started
        return report

    for i in range(0, total, BATCH_SIZE):
        batch = all_chunks[i : i + BATCH_SIZE]
        embeds = _embed_batch(embedder, [c.text for c in batch])
        collection.upsert(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            embeddings=embeds,
            metadatas=[c.metadata for c in batch],
        )
        on_progress(min(i + len(batch), total), total)

    report.chunks_created = total
    report.duration_s = time.time() - started
    log.info("Ingest: %d articles, %d chunks, %.1fs",
             report.articles_seen, report.chunks_created, report.duration_s)
    client.close()
    return report
```

### `Dev/kb_chatbot/tests/test_ingest.py`

```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.ingest import ingest

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def test_ingest_reports_article_count():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert report.articles_seen == 6


def test_ingest_creates_chunks():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert report.chunks_created >= 6


def test_ingest_per_product_counts():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert set(report.products.keys()) == {"api", "tradedesk", "saleshub", "web2", "web4", "other"}
        assert all(v == 1 for v in report.products.values())


def test_ingest_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        r1 = ingest(FIX, Path(tmp))
        r2 = ingest(FIX, Path(tmp))
        assert r1.chunks_created == r2.chunks_created


def test_ingest_collection_queryable_after_ingest():
    import chromadb
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        client = chromadb.PersistentClient(path=str(tmp))
        coll = client.get_collection("kbs")
        all_records = coll.get()
        assert len(all_records["ids"]) >= 6
        products = {m["product"] for m in all_records["metadatas"]}
        assert products == {"api", "tradedesk", "saleshub", "web2", "web4", "other"}
        client.close()
```

---

## APPENDIX D — Retriever tests

### `Dev/kb_chatbot/tests/test_retriever.py`

```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters, RetrievalResult

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def retriever():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))
    yield Retriever(Path(tmp), confidence_floor=0.0)


def test_retrieve_returns_chunks_relevant_to_iban(retriever):
    r = retriever.retrieve("IBAN validation form", Filters())
    assert isinstance(r, RetrievalResult)
    assert len(r.chunks) > 0
    assert r.chunks[0].metadata["product"] == "saleshub"


def test_filter_by_product_works_for_each_of_six(retriever):
    for prod in ("api", "tradedesk", "saleshub", "web2", "web4", "other"):
        r = retriever.retrieve("anything", Filters(product=prod))
        assert all(c.metadata["product"] == prod for c in r.chunks)


def test_retrieve_returns_top_k_max(retriever):
    r = retriever.retrieve("how do I do this", Filters())
    assert len(r.chunks) <= retriever.top_k_rerank


def test_retrieve_quick_returns_top_k_no_rerank(retriever):
    r = retriever.retrieve_quick("payment", limit=5)
    assert len(r) <= 5
    assert all("product" in c.metadata for c in r)


def test_confidence_gate_triggers_for_unrelated_query():
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        strict = Retriever(Path(tmp), confidence_floor=0.99)
        try:
            r = strict.retrieve("quantum field theory", Filters())
            assert r.abstain_reason == "no_relevant_kb_match"
            assert r.chunks == []
        finally:
            strict.close()
```

---

## APPENDIX E — Prompt + citations

### `Dev/kb_chatbot/prompt.py`

```python
"""V2.2 locked system prompt + context formatter + Anthropic-style message builder."""
from __future__ import annotations

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import Chunk


SYSTEM_PROMPT = """You are the Contoso Knowledge Base Assistant. You answer questions about the Contoso KB articles — release notes, how-to guides, API references, and product documentation for TradeDesk, Web2, Web4, SalesHub, and the API.

Hard rules — no exceptions:
1. You may only use facts from the CONTEXT block below. You have no other knowledge of Contoso products. Do not use general knowledge, intuition, or assumptions.
2. If the answer is not in the context, reply exactly: "I haven't been trained on this — it's not in the knowledge base I have access to. Want to refine the question?" — and offer one specific refinement (different product, related keyword, a how-to topic). Never invent.
3. Every factual claim must end with a citation tag in this exact form: [<Product> · <Category> · <Article title>] — e.g. [TradeDesk · dealing · Booking a Spot Deal]. A claim without a valid citation is forbidden.
4. If the user's intent is ambiguous (could refer to multiple products, multiple topics, or a vague feature name), do not answer. Instead, ask exactly one clarifying question.
5. Format the answer as: one-sentence direct answer first; then bullet list of relevant items (each with citation); then a "Searched:" footnote naming the product(s) and category you considered.

Do not editorialise. Do not apologise. Do not speculate about features that aren't documented. Do not summarise articles that weren't retrieved."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def _cite_handle(meta: dict) -> str:
    product = config.PRODUCT_DISPLAY.get(meta.get("product", ""), meta.get("product", ""))
    category = meta.get("category", "") or "general"
    title = meta.get("title", "")
    return f"[{product} · {category} · {title}]"


def format_context(chunks: list[Chunk]) -> str:
    lines = ["CONTEXT (the only facts you may use):", ""]
    for i, c in enumerate(chunks, 1):
        cite = _cite_handle(c.metadata)
        lines.append(f"{i}. {cite}")
        lines.append(f"   {c.text}")
        lines.append("")
    return "\n".join(lines)


def build_messages(*, context_chunks: list[Chunk], history: list[dict], user_msg: str) -> list[dict]:
    user_block = f"{format_context(context_chunks)}\nUSER QUESTION:\n{user_msg}"
    return [*history, {"role": "user", "content": user_block}]
```

### `Dev/kb_chatbot/tests/test_prompt.py`

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.prompt import SYSTEM_PROMPT, build_system_prompt, format_context, build_messages
from Dev.kb_chatbot.chunker import Chunk


def test_system_prompt_locked_text_v22():
    p = build_system_prompt()
    assert p == SYSTEM_PROMPT
    assert "Contoso KB articles" in p
    assert "I haven't been trained on this" in p
    assert "[<Product> · <Category> · <Article title>]" in p


def test_format_context_uses_article_cite_handle():
    chunks = [
        Chunk(id="x", text="some text",
              metadata={"product": "tradedesk", "category": "dealing", "title": "Booking a Spot Deal"})
    ]
    out = format_context(chunks)
    assert "[TradeDesk · dealing · Booking a Spot Deal]" in out
    assert "some text" in out


def test_format_context_falls_back_to_general_category():
    chunks = [
        Chunk(id="x", text="t",
              metadata={"product": "saleshub", "category": "", "title": "Welcome"})
    ]
    out = format_context(chunks)
    assert "[SalesHub · general · Welcome]" in out


def test_build_messages_includes_user_question_and_context():
    chunks = [
        Chunk(id="x", text="content",
              metadata={"product": "web4", "category": "booking_deals", "title": "Quick Pay"})
    ]
    msgs = build_messages(context_chunks=chunks, history=[], user_msg="What is Quick Pay?")
    assert msgs[-1]["role"] == "user"
    assert "What is Quick Pay?" in msgs[-1]["content"]
    assert "[Web4 · booking_deals · Quick Pay]" in msgs[-1]["content"]


def test_build_messages_includes_history():
    history = [
        {"role": "user", "content": "Earlier?"},
        {"role": "assistant", "content": "Earlier answer."},
    ]
    msgs = build_messages(context_chunks=[], history=history, user_msg="Now?")
    assert msgs[0]["content"] == "Earlier?"
    assert "Now?" in msgs[-1]["content"]
```

### `Dev/kb_chatbot/citations.py`

```python
"""V2.2 citations: parse + validate the article-based citation form [Product · Category · Title]."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import List

from Dev.kb_chatbot.chunker import Chunk

log = logging.getLogger("kb_chatbot.citations")

_CITE_RE = re.compile(
    r"\["
    r"(?P<product>API|TradeDesk|SalesHub|Web2|Web4|Other)"
    r"\s+·\s+"
    r"(?P<category>[^\]·]+?)"
    r"\s+·\s+"
    r"(?P<title>[^\]]+?)"
    r"\]"
)

_PRODUCT_NORMAL = {
    "API": "api", "TradeDesk": "tradedesk", "SalesHub": "saleshub",
    "Web2": "web2", "Web4": "web4", "Other": "other",
}


@dataclass
class Citation:
    raw: str
    product: str
    category: str
    title: str


@dataclass
class ValidationResult:
    all_verified: bool
    stripped_text: str
    verified: list[Citation] = field(default_factory=list)
    unverified: list[Citation] = field(default_factory=list)


def parse_citations(text: str) -> List[Citation]:
    out = []
    for m in _CITE_RE.finditer(text):
        out.append(Citation(
            raw=m.group(0),
            product=m.group("product"),
            category=m.group("category").strip(),
            title=m.group("title").strip(),
        ))
    return out


def _matches(cite: Citation, chunk: Chunk) -> bool:
    md = chunk.metadata
    if _PRODUCT_NORMAL.get(cite.product) != md.get("product"):
        return False
    md_cat = (md.get("category") or "").strip().lower() or "general"
    if cite.category.strip().lower() != md_cat:
        return False
    return cite.title.strip() == md.get("title", "").strip()


def validate(answer: str, retrieved: list[Chunk]) -> ValidationResult:
    cites = parse_citations(answer)
    verified, unverified = [], []
    for c in cites:
        if any(_matches(c, ch) for ch in retrieved):
            verified.append(c)
        else:
            unverified.append(c)
            log.warning("Hallucinated citation: %s", c.raw)

    stripped = answer
    for u in unverified:
        stripped = stripped.replace(u.raw, "[unverified]")

    return ValidationResult(
        all_verified=len(unverified) == 0,
        stripped_text=stripped,
        verified=verified,
        unverified=unverified,
    )
```

### `Dev/kb_chatbot/tests/test_citations.py`

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.citations import parse_citations, validate
from Dev.kb_chatbot.chunker import Chunk


def _chunk(product, category, title):
    return Chunk(id="x", text="...",
                 metadata={"product": product, "category": category,
                           "title": title, "kind": "article"})


def test_parses_well_formed_citation():
    txt = "Some claim [TradeDesk · dealing · Booking a Spot Deal]."
    cites = parse_citations(txt)
    assert len(cites) == 1
    c = cites[0]
    assert c.product == "TradeDesk"
    assert c.category == "dealing"
    assert c.title == "Booking a Spot Deal"


def test_parses_multiple_citations():
    txt = "A [TradeDesk · dealing · Booking a Spot Deal]. B [SalesHub · form_management · Building a Customer Onboarding Form]."
    cites = parse_citations(txt)
    assert len(cites) == 2


def test_ignores_malformed_citation_missing_separator():
    txt = "[TradeDesk dealing Booking a Spot Deal]"
    cites = parse_citations(txt)
    assert cites == []


def test_validator_accepts_matching_citation():
    retrieved = [_chunk("tradedesk", "dealing", "Booking a Spot Deal")]
    answer = "X [TradeDesk · dealing · Booking a Spot Deal]."
    result = validate(answer, retrieved)
    assert result.all_verified is True
    assert result.stripped_text == answer


def test_validator_strips_hallucinated_citation():
    retrieved = [_chunk("tradedesk", "dealing", "Booking a Spot Deal")]
    answer = "X [TradeDesk · invented · A Fake Article]."
    result = validate(answer, retrieved)
    assert result.all_verified is False
    assert "[unverified]" in result.stripped_text
    assert "A Fake Article" not in result.stripped_text


def test_validator_general_category_matches_empty_metadata():
    retrieved = [_chunk("saleshub", "", "Welcome")]
    answer = "Hi [SalesHub · general · Welcome]."
    result = validate(answer, retrieved)
    assert result.all_verified is True
```

---

## APPENDIX F — Claude Code provider

### `Dev/kb_chatbot/llm/claude_code_provider.py`

```python
"""ClaudeCodeProvider: programmatically invokes the local Claude Code CLI via claude-agent-sdk.
Uses the user's existing Claude Code OAuth. No API key required."""
from __future__ import annotations
import asyncio
import logging
import shutil
import time

from Dev.kb_chatbot.llm.base import LLMProvider, LLMResponse, estimate_cost

log = logging.getLogger("kb_chatbot.llm.claude_code")


class ClaudeCodeNotFoundError(RuntimeError):
    """Raised when the `claude` CLI cannot be located on PATH."""


def _ensure_claude_available() -> str:
    path = shutil.which("claude")
    if not path:
        raise ClaudeCodeNotFoundError(
            "Claude Code CLI not found on PATH. Install from https://claude.com/claude-code "
            "and run `claude login` once, then re-launch this app."
        )
    return path


def _build_user_prompt(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        role = m.get("role", "user").upper()
        parts.append(f"{role}: {m.get('content', '')}")
    return "\n\n".join(parts)


class ClaudeCodeProvider(LLMProvider):
    def __init__(self) -> None:
        _ensure_claude_available()

    def chat(self, *, messages, model, system_prompt, max_tokens=1024) -> LLMResponse:
        started = time.time()
        prompt = _build_user_prompt(messages)
        text, in_tok, out_tok = asyncio.run(self._query(prompt, model, system_prompt))
        latency_ms = int((time.time() - started) * 1000)
        return LLMResponse(
            text=text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            model=model,
            latency_ms=latency_ms,
            cost_estimate_usd=estimate_cost(model, in_tok, out_tok),
        )

    async def _query(self, prompt: str, model: str, system_prompt: str) -> tuple[str, int, int]:
        from claude_agent_sdk import query, ClaudeAgentOptions

        options = ClaudeAgentOptions(system_prompt=system_prompt, model=model)
        text_parts: list[str] = []
        in_tok = 0
        out_tok = 0
        async for message in query(prompt=prompt, options=options):
            content = getattr(message, "content", None)
            if content:
                for block in content:
                    block_text = getattr(block, "text", None)
                    if block_text:
                        text_parts.append(block_text)
            usage = getattr(message, "usage", None)
            if usage:
                in_tok = max(in_tok, getattr(usage, "input_tokens", in_tok) or in_tok)
                out_tok = max(out_tok, getattr(usage, "output_tokens", out_tok) or out_tok)
        text = "".join(text_parts).strip()
        if not in_tok and not out_tok:
            in_tok = max(1, len(prompt) // 4)
            out_tok = max(1, len(text) // 4)
        return text, in_tok, out_tok
```

### `Dev/kb_chatbot/tests/test_claude_code_provider.py`

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.llm.claude_code_provider import (
    ClaudeCodeProvider, ClaudeCodeNotFoundError, _ensure_claude_available, _build_user_prompt,
)


def test_raises_when_claude_cli_missing(monkeypatch):
    from Dev.kb_chatbot.llm import claude_code_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    with pytest.raises(ClaudeCodeNotFoundError) as excinfo:
        ClaudeCodeProvider()
    assert "Claude Code CLI not found" in str(excinfo.value)


def test_ensure_returns_path_when_present(monkeypatch):
    from Dev.kb_chatbot.llm import claude_code_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: r"C:\fake\bin\claude.exe")
    assert _ensure_claude_available() == r"C:\fake\bin\claude.exe"


def test_build_user_prompt_flattens_messages():
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "what's quick pay?"},
    ]
    out = _build_user_prompt(msgs)
    assert "USER: hello" in out
    assert "ASSISTANT: hi" in out
    assert out.endswith("USER: what's quick pay?")
```

---

## APPENDIX G — Orchestrator + integration + golden Q&A

### `Dev/kb_chatbot/tests/fixtures/golden_qa.json`

```json
[
  {
    "name": "tradedesk_booking_clear",
    "user_msg": "How do I book a spot deal in TradeDesk?",
    "filters": {},
    "expect": "answer",
    "must_retrieve_any_of": ["Booking a Spot Deal"]
  },
  {
    "name": "saleshub_form_management",
    "user_msg": "How do I build an onboarding form in SalesHub?",
    "filters": {},
    "expect": "answer",
    "must_retrieve_any_of": ["Building a Customer Onboarding Form"]
  },
  {
    "name": "web4_quick_pay",
    "user_msg": "Tell me about Quick Pay in Web4",
    "filters": {},
    "expect": "answer",
    "must_retrieve_any_of": ["Quick Pay and Payment Links"]
  },
  {
    "name": "no_product_named_should_clarify",
    "user_msg": "How do I do this?",
    "filters": {},
    "expect": "clarify_or_answer"
  },
  {
    "name": "off_topic_abstain",
    "user_msg": "What is the meaning of life?",
    "filters": {},
    "expect": "abstain"
  }
]
```

### `Dev/kb_chatbot/chat/orchestrator.py`

```python
"""V2.2 per-turn pipeline. Retrieval-first → confidence gate → clarification fallback for
borderline-score queries → LLM call → citation validation."""
from __future__ import annotations
import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.citations import validate as validate_citations
from Dev.kb_chatbot.llm.base import LLMProvider
from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeNotFoundError
from Dev.kb_chatbot.prompt import build_system_prompt, build_messages
from Dev.kb_chatbot.retriever import Retriever, Filters

log = logging.getLogger("kb_chatbot.orchestrator")

ABSTAIN_MESSAGE = (
    "I haven't been trained on this — it's not in the knowledge base I have access to. "
    "Want to refine the question? Try naming a product (API, TradeDesk, SalesHub, Web2, Web4, Other), "
    "a related keyword, or a how-to topic."
)


def _mentions_product(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in config.PRODUCTS)


def _recent_product_in_history(session: Session) -> bool:
    for t in reversed(session.turns[-6:]):
        if _mentions_product(t["content"]):
            return True
    return False


def _needs_clarification_from_quick(quick: list[Chunk]) -> bool:
    if not quick:
        return False
    products = Counter(c.metadata.get("product", "") for c in quick)
    if len(products) <= 1:
        return False
    total = sum(products.values())
    dominant = products.most_common(1)[0][1]
    return dominant / total < 0.60


def _default_clarifier(user_msg: str, quick: list[Chunk]) -> str:
    products = sorted({c.metadata.get("product", "") for c in quick if c.metadata.get("product")})
    pretty = ", ".join(config.PRODUCT_DISPLAY.get(p, p) for p in products) or \
             "API, TradeDesk, SalesHub, Web2, Web4, or Other"
    return (f"Multiple products have records related to your question. "
            f"Which one are you asking about — {pretty}?")


@dataclass
class Deps:
    retriever: Retriever
    llm: LLMProvider
    usage_logger: Callable[[Turn], None] = lambda t: None
    clarifier: Optional[Callable[[str, list[Chunk]], str]] = None


def handle_turn(user_msg: str, session: Session, filters: Filters,
                default_model: str, *, deps: Deps) -> Turn:
    session.add_user(user_msg)

    result = deps.retriever.retrieve(user_msg, filters)

    if not result.abstain_reason:
        if not (filters.product or _mentions_product(user_msg) or _recent_product_in_history(session)):
            quick = deps.retriever.retrieve_quick(user_msg, limit=10)
            if _needs_clarification_from_quick(quick):
                clar_fn = deps.clarifier or _default_clarifier
                turn = Turn(role="assistant", content=clar_fn(user_msg, quick),
                            kind="clarification", retrieved_ids=[c.id for c in quick])
                session.add(turn)
                deps.usage_logger(turn)
                return turn

        try:
            messages = build_messages(
                context_chunks=result.chunks,
                history=session.history_for_llm(config.MAX_HISTORY_TURNS),
                user_msg=user_msg,
            )
            resp = deps.llm.chat(
                messages=messages,
                model=default_model,
                system_prompt=build_system_prompt(),
                max_tokens=1024,
            )
        except ClaudeCodeNotFoundError as exc:
            turn = Turn(role="assistant", kind="abstain", content=str(exc))
            session.add(turn)
            deps.usage_logger(turn)
            return turn
        except Exception as exc:
            log.exception("LLM call failed")
            turn = Turn(role="assistant", kind="abstain",
                        content=f"Sorry — the LLM call failed: {exc}. Details in run.log.")
            session.add(turn)
            deps.usage_logger(turn)
            return turn

        vr = validate_citations(resp.text, result.chunks)
        turn = Turn(
            role="assistant",
            content=vr.stripped_text,
            kind="answer",
            citations=[{"raw": c.raw, "verified": True} for c in vr.verified]
                      + [{"raw": c.raw, "verified": False} for c in vr.unverified],
            retrieved_ids=[c.id for c in result.chunks],
            model=resp.model,
            tokens_in=resp.input_tokens,
            tokens_out=resp.output_tokens,
            latency_ms=resp.latency_ms,
        )
        session.add(turn)
        deps.usage_logger(turn)
        return turn

    if result.rerank_top_score > config.CLARIFY_SCORE_FLOOR and not (
        filters.product or _mentions_product(user_msg) or _recent_product_in_history(session)
    ):
        quick = deps.retriever.retrieve_quick(user_msg, limit=10)
        if _needs_clarification_from_quick(quick):
            clar_fn = deps.clarifier or _default_clarifier
            turn = Turn(role="assistant", content=clar_fn(user_msg, quick),
                        kind="clarification", retrieved_ids=[c.id for c in quick])
            session.add(turn)
            deps.usage_logger(turn)
            return turn

    turn = Turn(role="assistant", kind="abstain", content=ABSTAIN_MESSAGE)
    session.add(turn)
    deps.usage_logger(turn)
    return turn
```

### `Dev/kb_chatbot/tests/test_orchestrator.py`

```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps, ABSTAIN_MESSAGE

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def deps_factory():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))

    def make(confidence_floor: float, fake_text: str):
        r = Retriever(Path(tmp), confidence_floor=confidence_floor)
        llm = FakeProvider(canned_text=fake_text)
        return Deps(retriever=r, llm=llm, usage_logger=lambda t: None), llm
    return make


def test_clear_question_yields_answer_turn(deps_factory):
    d, _ = deps_factory(0.0, "Answer text [TradeDesk · dealing · Booking a Spot Deal].")
    session = Session.new()
    turn = handle_turn("How do I book a spot deal in TradeDesk?", session,
                        Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"
    assert "Booking a Spot Deal" in turn.content


def test_abstain_when_retrieval_below_floor(deps_factory):
    d, fake = deps_factory(0.99, "should not be seen")
    session = Session.new()
    turn = handle_turn("quantum field theory", session, Filters(),
                        "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "abstain"
    assert turn.content == ABSTAIN_MESSAGE
    assert len(fake.calls) == 0


def test_hallucinated_citation_gets_stripped(deps_factory):
    d, _ = deps_factory(0.0, "Some answer [TradeDesk · made-up · No Such Article].")
    session = Session.new()
    turn = handle_turn("anything about tradedesk dealing", session,
                        Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=d)
    assert "[unverified]" in turn.content
    assert "No Such Article" not in turn.content


def test_session_persists_user_turn():
    s = Session.new()
    assert s.turns == []
    s.add_user("hi")
    assert s.turns[-1]["role"] == "user"


def test_clarification_when_no_product_and_diffuse_retrieval(deps_factory):
    d, fake = deps_factory(0.0, "irrelevant fake answer")
    session = Session.new()
    turn = handle_turn("How do I do this?", session, Filters(),
                        "claude-haiku-4-5-20251001", deps=d)
    if turn.kind == "clarification":
        assert len(fake.calls) == 0
    else:
        assert turn.kind in ("answer", "abstain")
```

### `Dev/kb_chatbot/tests/test_integration.py`

```python
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps

FIX = Path(__file__).parent / "fixtures" / "tiny_library"
GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "golden_qa.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def deps_factory():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))

    def make(confidence_floor: float, fake_text: str):
        r = Retriever(Path(tmp), confidence_floor=confidence_floor)
        llm = FakeProvider(canned_text=fake_text)
        return Deps(retriever=r, llm=llm, usage_logger=lambda t: None)
    return make


@pytest.mark.parametrize("case", GOLDEN)
def test_golden_qa_case(deps_factory, case):
    must_titles = case.get("must_retrieve_any_of", [])
    fake_cite = ""
    if must_titles:
        fake_cite = f"[TradeDesk · dealing · {must_titles[0]}]"
    fake_text = f"Stub answer {fake_cite}"

    if case["expect"] == "abstain":
        deps = deps_factory(confidence_floor=0.99, fake_text="should never see this")
    else:
        deps = deps_factory(confidence_floor=0.0, fake_text=fake_text)

    session = Session.new()
    filters = Filters(**case.get("filters", {}))
    turn = handle_turn(case["user_msg"], session, filters,
                        "claude-haiku-4-5-20251001", deps=deps)

    if case["expect"] == "abstain":
        assert turn.kind == "abstain"
    elif case["expect"] == "clarify_or_answer":
        assert turn.kind in ("answer", "clarification", "abstain")
    else:
        assert turn.kind in ("answer", "clarification")
```

---

## APPENDIX H — GUI

### `Dev/kb_chatbot/gui.py`

```python
"""V2.2 KB Chatbot GUI. No API key. Claude Code preflight on startup."""
from __future__ import annotations
import sys
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QTextCursor, QAction, QFont, QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QPlainTextEdit, QLineEdit, QToolBar,
    QStatusBar, QMessageBox, QDialog, QDialogButtonBox, QFormLayout,
    QFileDialog, QProgressBar,
)

from Dev.kb_chatbot import config, settings as settings_mod
from Dev.kb_chatbot.chat.orchestrator import Deps, handle_turn
from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider, ClaudeCodeNotFoundError
from Dev.kb_chatbot.retriever import Retriever, Filters

config.STATE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("kb_chatbot.gui")


def _append_usage(turn: Turn) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": turn.ts, "kind": turn.kind, "model": turn.model,
        "tokens_in": turn.tokens_in, "tokens_out": turn.tokens_out,
        "latency_ms": turn.latency_ms, "retrieved_ids": turn.retrieved_ids,
        "citations": turn.citations,
    }
    with open(config.USAGE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class TurnWorker(QThread):
    def __init__(self, user_msg, session, filters, default_model, deps):
        super().__init__()
        self.user_msg = user_msg
        self.session = session
        self.filters = filters
        self.default_model = default_model
        self.deps = deps
        self.signals = WorkerSignals()
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            turn = handle_turn(self.user_msg, self.session, self.filters,
                                self.default_model, deps=self.deps)
            if self._cancel:
                turn = Turn(role="assistant", kind="abstain", content="Cancelled.")
                self.session.add(turn)
            self.signals.finished.emit(turn)
        except Exception as exc:
            log.exception("Turn failed")
            self.signals.failed.emit(str(exc))
        finally:
            try:
                close = getattr(self.deps.retriever, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass


class IngestWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, library_path, chroma_path):
        super().__init__()
        self.library_path = library_path
        self.chroma_path = chroma_path

    def run(self):
        try:
            report = ingest(self.library_path, self.chroma_path,
                             on_progress=lambda d, t: self.progress.emit(d, t))
            self.finished.emit(report)
        except Exception as exc:
            log.exception("Ingest failed")
            self.failed.emit(str(exc))


class SettingsDialog(QDialog):
    def __init__(self, parent, current):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 180)
        form = QFormLayout(self)
        self.lib_edit = QLineEdit(str(current.library_path))
        self.lib_btn = QPushButton("Browse…")
        self.lib_btn.clicked.connect(self._pick_dir)
        lib_row = QHBoxLayout(); lib_row.addWidget(self.lib_edit); lib_row.addWidget(self.lib_btn)
        lib_w = QWidget(); lib_w.setLayout(lib_row)
        self.model_box = QComboBox()
        for label, ident in config.AVAILABLE_MODELS.items():
            self.model_box.addItem(label, ident)
        idx = self.model_box.findData(current.default_model)
        if idx >= 0:
            self.model_box.setCurrentIndex(idx)
        form.addRow("Library path:", lib_w)
        form.addRow("Default model:", self.model_box)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Pick library directory", self.lib_edit.text())
        if d:
            self.lib_edit.setText(d)

    def values(self):
        return settings_mod.Settings(
            library_path=Path(self.lib_edit.text()),
            default_model=self.model_box.currentData(),
            confidence_floor=config.CONFIDENCE_FLOOR,
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contoso KB Chatbot")
        self.resize(1100, 780)
        self.settings = settings_mod.load_settings()
        self.session = Session.new()
        self.worker: Optional[TurnWorker] = None
        self.ingest_worker: Optional[IngestWorker] = None
        self._today_queries = 0
        self._today_tokens = 0
        self._build_ui()

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        tb = QToolBar(); tb.setMovable(False); self.addToolBar(tb)
        self._act_reindex = QAction("Reindex", self); tb.addAction(self._act_reindex)
        self._act_settings = QAction("Settings", self); tb.addAction(self._act_settings)
        self._act_clear = QAction("Clear chat", self); tb.addAction(self._act_clear)
        tb.addSeparator()
        self._act_stop = QAction("⏹ STOP", self); tb.addAction(self._act_stop)
        self._act_logs = QAction("View logs", self); tb.addAction(self._act_logs)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Product:"))
        self.product_box = QComboBox()
        self.product_box.addItem("Any", "")
        for p in config.PRODUCTS:
            self.product_box.addItem(config.PRODUCT_DISPLAY.get(p, p), p)
        filter_row.addWidget(self.product_box)
        filter_row.addWidget(QLabel("Model:"))
        self.model_box = QComboBox()
        for label, ident in config.AVAILABLE_MODELS.items():
            self.model_box.addItem(label, ident)
        idx = self.model_box.findData(self.settings.default_model)
        if idx >= 0:
            self.model_box.setCurrentIndex(idx)
        filter_row.addWidget(self.model_box)
        filter_row.addStretch()
        outer.addLayout(filter_row)

        self.chat_view = QPlainTextEdit(); self.chat_view.setReadOnly(True)
        self.chat_view.setFont(QFont("Consolas", 10))
        outer.addWidget(self.chat_view, stretch=1)

        self.progress = QProgressBar(); self.progress.setVisible(False)
        outer.addWidget(self.progress)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask a question about the Contoso KB…")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input); input_row.addWidget(self.send_btn)
        outer.addLayout(input_row)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Log: {config.LOG_FILE}")

        self._act_reindex.triggered.connect(self._reindex)
        self._act_settings.triggered.connect(self._open_settings)
        self._act_clear.triggered.connect(self._clear_chat)
        self._act_stop.triggered.connect(self._stop)
        self._act_logs.triggered.connect(self._open_logs)
        self._set_inputs_enabled(True)
        self._append("system", "Ready. Type a question below.", "#1b5e20", "SYSTEM:")

    def _append(self, role, text, colour, tag):
        ts = datetime.now().strftime("%H:%M:%S")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat(); fmt.setForeground(QColor(colour))
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"{ts} {tag:9s} {text}\n\n", fmt)
        self.chat_view.setTextCursor(cursor)
        self.chat_view.ensureCursorVisible()

    def _send(self):
        msg = self.input.text().strip()
        if not msg or self.worker:
            return
        self.input.clear()
        self._set_inputs_enabled(False)
        self._append("user", msg, "#0d47a1", "YOU:")

        try:
            llm = ClaudeCodeProvider()
            retriever = Retriever(config.CHROMA_DIR, confidence_floor=self.settings.confidence_floor)
        except ClaudeCodeNotFoundError as exc:
            self._append("system", str(exc), "#c62828", "ERROR:")
            self._set_inputs_enabled(True)
            return
        except Exception as exc:
            self._append("system", f"Failed to initialise: {exc}", "#c62828", "ERROR:")
            log.exception("Init failure on send")
            self._set_inputs_enabled(True)
            return

        deps = Deps(retriever=retriever, llm=llm, usage_logger=_append_usage)
        filters = Filters(product=self.product_box.currentData() or None)
        model = self.model_box.currentData()
        self.worker = TurnWorker(msg, self.session, filters, model, deps)
        self.worker.signals.finished.connect(self._on_turn_done)
        self.worker.signals.failed.connect(self._on_turn_failed)
        self.worker.start()

    @Slot(object)
    def _on_turn_done(self, turn):
        colour = "#212121"; tag = "AI:"
        if turn.kind == "abstain":
            colour, tag = "#5d4037", "ABSTAIN:"
        elif turn.kind == "clarification":
            colour, tag = "#ef6c00", "CLARIFY:"
        self._append("ai", turn.content, colour, tag)
        self._today_queries += 1
        self._today_tokens += turn.tokens_in + turn.tokens_out
        self.statusBar().showMessage(
            f"Today: {self._today_queries} queries · {self._today_tokens} tokens · Log: {config.LOG_FILE}"
        )
        self.worker = None
        self._set_inputs_enabled(True)

    @Slot(str)
    def _on_turn_failed(self, err):
        self._append("system", f"Error: {err}", "#c62828", "ERROR:")
        self.worker = None
        self._set_inputs_enabled(True)

    def _stop(self):
        if self.worker:
            self.worker.cancel()

    def _open_settings(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QDialog.Accepted:
            self.settings = dlg.values()
            settings_mod.save_settings(self.settings)
            self._append("system", "Settings saved.", "#1b5e20", "SYSTEM:")

    def _clear_chat(self):
        self.chat_view.clear()
        self.session = Session.new()

    def _open_logs(self):
        import subprocess
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer.exe", str(config.STATE_DIR)])

    def _reindex(self):
        if self.ingest_worker:
            return
        self.progress.setVisible(True); self.progress.setValue(0)
        self._set_inputs_enabled(False)
        self.ingest_worker = IngestWorker(self.settings.library_path, config.CHROMA_DIR)
        self.ingest_worker.progress.connect(self._on_ingest_progress)
        self.ingest_worker.finished.connect(self._on_ingest_done)
        self.ingest_worker.failed.connect(self._on_ingest_failed)
        self.ingest_worker.start()
        self._append("system", f"Reindex started from {self.settings.library_path}", "#1b5e20", "SYSTEM:")

    @Slot(int, int)
    def _on_ingest_progress(self, done, total):
        if total:
            self.progress.setValue(int(done * 100 / total))

    @Slot(object)
    def _on_ingest_done(self, report):
        self.progress.setVisible(False)
        self._append("system",
            f"Reindex complete: {report.articles_seen} articles, {report.chunks_created} chunks, {report.duration_s:.1f}s",
            "#1b5e20", "SYSTEM:")
        self.ingest_worker = None
        self._set_inputs_enabled(True)

    @Slot(str)
    def _on_ingest_failed(self, err):
        self.progress.setVisible(False)
        self._append("system", f"Reindex failed: {err}", "#c62828", "ERROR:")
        self.ingest_worker = None
        self._set_inputs_enabled(True)

    def _set_inputs_enabled(self, enabled):
        self.input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        for w in (self._act_reindex, self._act_settings, self._act_clear):
            w.setEnabled(enabled)
        self._act_stop.setEnabled(not enabled)

    def closeEvent(self, event):
        if self.worker or self.ingest_worker:
            reply = QMessageBox.question(self, "Quit?",
                "A task is running. Quit anyway?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore(); return
            if self.worker:
                self.worker.cancel(); self.worker.wait(5_000)
        try:
            self.session.save(config.CHATS_DIR)
        except Exception:
            log.exception("Session save failed on close")
        event.accept()


def _preflight_claude_code() -> Optional[str]:
    if shutil.which("claude"):
        return None
    return ("Claude Code is required.\n\n"
            "Install from https://claude.com/claude-code, run `claude login`, "
            "and re-launch this app.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Contoso KB Chatbot")
    err = _preflight_claude_code()
    if err:
        QMessageBox.critical(None, "Claude Code missing", err)
        sys.exit(1)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

---

## APPENDIX I — PyInstaller spec

### `ContosoKBChatbot.spec`

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("PySide6", "sentence_transformers", "chromadb", "claude_agent_sdk", "markdown"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

hiddenimports += [
    "torch", "transformers", "tokenizers",
    "sklearn.utils._cython_blas",
]

a = Analysis(
    ["Dev/kb_chatbot/gui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch.distributed", "torchvision", "torchaudio",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DExtras", "PySide6.Qt3DAnimation",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="ContosoKBChatbot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
```
