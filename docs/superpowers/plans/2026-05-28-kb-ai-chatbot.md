# KB AI Chatbot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Build a local Windows desktop app (`ContosoKBChatbot.exe`) that lets the team ask questions grounded **strictly** in the scraped Contoso KB library, with citations, abstention when no source matches, and clarifying questions when intent is ambiguous.

**Architecture:** Single-pass RAG. Local sentence-transformers embeddings + ChromaDB + cross-encoder rerank + confidence gate → optional Anthropic LLM call → post-hoc citation validation. PySide6 chat UI. PyInstaller `.exe`. Anthropic only at MVP (provider abstraction designed for OpenAI later). API keys per-teammate via Windows keyring.

**Tech Stack:** Python 3.10+, PySide6, sentence-transformers, ChromaDB, anthropic SDK, keyring, PyInstaller. Tests via pytest.

**Spec:** `docs/superpowers/specs/2026-05-28-kb-ai-chatbot-design.md`

This is a **no-git environment** — no `git commit` steps. Verification is the passing test run after each task. The implementer must NOT run git commands.

All commands assume CWD is the Knowledge Base root. Python is `scraper\venv\Scripts\python.exe` (existing venv — reused; new deps installed into it).

---

## Ground rules for every task

- **TDD where logic exists:** failing test first, run to confirm fail, implement, run to confirm pass.
- **Static config/scaffolding tasks** verify by direct import or file-existence check.
- **Reproduce code character-for-character** from the prescribed blocks.
- **Do NOT modify any file outside the task's declared scope.** This protects the scraper + already-shipped pieces.
- **Do NOT run git.**

---

## File Map (locked at plan time)

```
Knowledge Base/
└── Dev/
    └── kb_chatbot/
        ├── __init__.py
        ├── requirements.txt
        ├── config.py
        ├── settings.py
        ├── chunker.py
        ├── ingest.py
        ├── retriever.py
        ├── prompt.py
        ├── citations.py
        ├── llm/
        │   ├── __init__.py
        │   ├── base.py
        │   ├── anthropic_provider.py
        │   └── fake_provider.py
        ├── chat/
        │   ├── __init__.py
        │   ├── session.py
        │   └── orchestrator.py
        ├── gui.py
        └── tests/
            ├── fixtures/
            │   ├── tiny_library/
            │   └── golden_qa.json
            ├── conftest.py
            ├── test_settings.py
            ├── test_chunker.py
            ├── test_ingest.py
            ├── test_retriever.py
            ├── test_prompt.py
            ├── test_citations.py
            ├── test_llm.py
            ├── test_orchestrator.py
            └── test_integration.py
ContosoKBChatbot.spec
build_chatbot_exe.bat
```

---

## Task 1: Scaffold + config + settings (TDD)

**Files:**
- Create: `Dev/kb_chatbot/__init__.py`, `Dev/kb_chatbot/llm/__init__.py`, `Dev/kb_chatbot/chat/__init__.py`, `Dev/kb_chatbot/tests/__init__.py`
- Create: `Dev/kb_chatbot/requirements.txt`
- Create: `Dev/kb_chatbot/config.py`
- Create: `Dev/kb_chatbot/settings.py`
- Create: `Dev/kb_chatbot/tests/conftest.py`
- Create: `Dev/kb_chatbot/tests/test_settings.py`

- [ ] **Step 1: Create directory tree + empty marker files**

```powershell
New-Item -ItemType Directory -Force "Dev\kb_chatbot\llm"             | Out-Null
New-Item -ItemType Directory -Force "Dev\kb_chatbot\chat"            | Out-Null
New-Item -ItemType Directory -Force "Dev\kb_chatbot\tests\fixtures"  | Out-Null
```
Then write four marker files, each containing one comment line:
- `Dev/kb_chatbot/__init__.py` → `# Contoso KB Chatbot package`
- `Dev/kb_chatbot/llm/__init__.py` → `# llm provider package`
- `Dev/kb_chatbot/chat/__init__.py` → `# chat session + orchestrator`
- `Dev/kb_chatbot/tests/__init__.py` → `# tests`

- [ ] **Step 2: Write `Dev/kb_chatbot/requirements.txt`**

```
PySide6>=6.6.0
sentence-transformers>=2.7
chromadb>=0.5
anthropic>=0.34
keyring>=24
markdown>=3.6
pytest>=7.4.0
```

- [ ] **Step 3: Install new deps into the existing venv**

```powershell
scraper\venv\Scripts\python.exe -m pip install "sentence-transformers>=2.7" "chromadb>=0.5" "anthropic>=0.34" "keyring>=24" "markdown>=3.6"
```

- [ ] **Step 4: Create `Dev/kb_chatbot/config.py`** with content from **APPENDIX A — config.py**.

- [ ] **Step 5: Write the failing test `Dev/kb_chatbot/tests/test_settings.py`** with content from **APPENDIX A — test_settings.py**.

- [ ] **Step 6: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_settings.py -v 2>&1 | Select-Object -First 15
```
Expected: `ModuleNotFoundError: No module named 'Dev.kb_chatbot.settings'`.

- [ ] **Step 7: Create `Dev/kb_chatbot/settings.py`** with content from **APPENDIX A — settings.py**.

- [ ] **Step 8: Create `Dev/kb_chatbot/tests/conftest.py`** with content from **APPENDIX A — conftest.py**.

- [ ] **Step 9: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_settings.py -v
```
Expected: 4 passed.

---

## Task 2: Chunker + tiny-library fixture (TDD)

**Files:**
- Create: 3 JSON files at `Dev/kb_chatbot/tests/fixtures/tiny_library/<product>/versions/<ver>.json`
- Create: `Dev/kb_chatbot/tests/test_chunker.py`
- Create: `Dev/kb_chatbot/chunker.py`

- [ ] **Step 1: Create tiny-library fixture files** with content from **APPENDIX B — tiny_library**.

The three files (all must be written using the Write tool with the exact JSON given in Appendix B):
- `Dev/kb_chatbot/tests/fixtures/tiny_library/tradedesk/versions/3.0.1.9.json`
- `Dev/kb_chatbot/tests/fixtures/tiny_library/web4/versions/4.0.3.0.json`
- `Dev/kb_chatbot/tests/fixtures/tiny_library/saleshub/versions/2.0.2.1.json`

Create parent dirs first via `New-Item -ItemType Directory -Force "Dev\kb_chatbot\tests\fixtures\tiny_library\tradedesk\versions"` (repeat for web4, saleshub).

- [ ] **Step 2: Write the failing test `Dev/kb_chatbot/tests/test_chunker.py`** with content from **APPENDIX B — test_chunker.py**.

- [ ] **Step 3: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_chunker.py -v 2>&1 | Select-Object -First 12
```

- [ ] **Step 4: Create `Dev/kb_chatbot/chunker.py`** with content from **APPENDIX B — chunker.py**.

- [ ] **Step 5: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_chunker.py -v
```
Expected: 7 passed.

---

## Task 3: Ingest (library → ChromaDB) (TDD)

**Files:**
- Create: `Dev/kb_chatbot/tests/test_ingest.py`
- Create: `Dev/kb_chatbot/ingest.py`

This task uses **real sentence-transformers + real ChromaDB** against the tiny library. First run downloads the embed model (~22 MB).

- [ ] **Step 1: Pre-download the embedding model** (avoids first-run hitch inside tests)

```powershell
scraper\venv\Scripts\python.exe -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); print('model cached')"
```
Expected: `model cached`. First time runs ~30s download.

- [ ] **Step 2: Write the failing test `Dev/kb_chatbot/tests/test_ingest.py`** with content from **APPENDIX C — test_ingest.py**.

- [ ] **Step 3: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ingest.py -v 2>&1 | Select-Object -First 12
```

- [ ] **Step 4: Create `Dev/kb_chatbot/ingest.py`** with content from **APPENDIX C — ingest.py**.

- [ ] **Step 5: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_ingest.py -v
```
Expected: 5 passed.

---

## Task 4: Retriever (embedding + ChromaDB + rerank + gate) (TDD)

**Files:**
- Create: `Dev/kb_chatbot/tests/test_retriever.py`
- Create: `Dev/kb_chatbot/retriever.py`

- [ ] **Step 1: Pre-download the cross-encoder**

```powershell
scraper\venv\Scripts\python.exe -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2'); print('reranker cached')"
```

- [ ] **Step 2: Write the failing test `Dev/kb_chatbot/tests/test_retriever.py`** with content from **APPENDIX D — test_retriever.py**.

- [ ] **Step 3: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_retriever.py -v 2>&1 | Select-Object -First 12
```

- [ ] **Step 4: Create `Dev/kb_chatbot/retriever.py`** with content from **APPENDIX D — retriever.py**.

- [ ] **Step 5: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_retriever.py -v
```
Expected: 5 passed.

---

## Task 5: Prompt + citations (TDD)

**Files:**
- Create: `Dev/kb_chatbot/tests/test_prompt.py`
- Create: `Dev/kb_chatbot/tests/test_citations.py`
- Create: `Dev/kb_chatbot/prompt.py`
- Create: `Dev/kb_chatbot/citations.py`

- [ ] **Step 1: Write the failing test `Dev/kb_chatbot/tests/test_prompt.py`** with content from **APPENDIX E — test_prompt.py**.

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_prompt.py -v 2>&1 | Select-Object -First 12
```

- [ ] **Step 3: Create `Dev/kb_chatbot/prompt.py`** with content from **APPENDIX E — prompt.py**.

- [ ] **Step 4: Run — confirm prompt tests PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_prompt.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Write the failing test `Dev/kb_chatbot/tests/test_citations.py`** with content from **APPENDIX E — test_citations.py**.

- [ ] **Step 6: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_citations.py -v 2>&1 | Select-Object -First 12
```

- [ ] **Step 7: Create `Dev/kb_chatbot/citations.py`** with content from **APPENDIX E — citations.py**.

- [ ] **Step 8: Run — confirm citation tests PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_citations.py -v
```
Expected: 6 passed.

---

## Task 6: LLM provider abstraction + Anthropic + fake (TDD)

**Files:**
- Create: `Dev/kb_chatbot/tests/test_llm.py`
- Create: `Dev/kb_chatbot/llm/base.py`
- Create: `Dev/kb_chatbot/llm/anthropic_provider.py`
- Create: `Dev/kb_chatbot/llm/fake_provider.py`

- [ ] **Step 1: Write the failing test `Dev/kb_chatbot/tests/test_llm.py`** with content from **APPENDIX F — test_llm.py**.

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_llm.py -v 2>&1 | Select-Object -First 12
```

- [ ] **Step 3: Create `Dev/kb_chatbot/llm/base.py`** with content from **APPENDIX F — base.py**.

- [ ] **Step 4: Create `Dev/kb_chatbot/llm/fake_provider.py`** with content from **APPENDIX F — fake_provider.py**.

- [ ] **Step 5: Create `Dev/kb_chatbot/llm/anthropic_provider.py`** with content from **APPENDIX F — anthropic_provider.py**.

- [ ] **Step 6: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_llm.py -v
```
Expected: 3 passed.

---

## Task 7: Session + orchestrator + integration tests (TDD)

**Files:**
- Create: `Dev/kb_chatbot/tests/fixtures/golden_qa.json`
- Create: `Dev/kb_chatbot/tests/test_orchestrator.py`
- Create: `Dev/kb_chatbot/tests/test_integration.py`
- Create: `Dev/kb_chatbot/chat/session.py`
- Create: `Dev/kb_chatbot/chat/orchestrator.py`

- [ ] **Step 1: Create `Dev/kb_chatbot/tests/fixtures/golden_qa.json`** with content from **APPENDIX G — golden_qa.json**.

- [ ] **Step 2: Write the failing test `Dev/kb_chatbot/tests/test_orchestrator.py`** with content from **APPENDIX G — test_orchestrator.py**.

- [ ] **Step 3: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator.py -v 2>&1 | Select-Object -First 12
```

- [ ] **Step 4: Create `Dev/kb_chatbot/chat/session.py`** with content from **APPENDIX G — session.py**.

- [ ] **Step 5: Create `Dev/kb_chatbot/chat/orchestrator.py`** with content from **APPENDIX G — orchestrator.py**.

- [ ] **Step 6: Run — confirm orchestrator tests PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator.py -v
```
Expected: 5 passed.

- [ ] **Step 7: Write the golden Q&A integration test `Dev/kb_chatbot/tests/test_integration.py`** with content from **APPENDIX G — test_integration.py**.

- [ ] **Step 8: Run — confirm integration PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_integration.py -v
```
Expected: 5 parametrised cases pass.

- [ ] **Step 9: Full test suite stays green**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/ -v
scraper\venv\Scripts\python.exe -m pytest tests/ -v
```
Expected: chatbot tests all green (≥35 total); scraper suite stays at 50 green.

---

## Task 8: GUI (PySide6 chat window)

**Files:**
- Create: `Dev/kb_chatbot/gui.py`

- [ ] **Step 1: Create `Dev/kb_chatbot/gui.py`** with content from **APPENDIX H — gui.py**.

- [ ] **Step 2: Smoke-test the GUI module imports** (does NOT launch QApplication)

```powershell
scraper\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from Dev.kb_chatbot.gui import MainWindow; print('chatbot gui imports OK')"
```
Expected: `chatbot gui imports OK`.

- [ ] **Step 3: Launch the GUI from source briefly to confirm it boots** (Python process killed after a few seconds — do not interact):

```powershell
Start-Process -FilePath "scraper\venv\Scripts\python.exe" -ArgumentList "Dev\kb_chatbot\gui.py" -PassThru | ForEach-Object { Start-Sleep -Seconds 6; if (-not $_.HasExited) { Write-Host "Boot OK"; Stop-Process -Id $_.Id -Force } else { Write-Host "Process exited prematurely; check logs"; exit 1 } }
```
Expected: `Boot OK`.

---

## Task 9: PyInstaller spec + build (`ContosoKBChatbot.exe`)

**Files:**
- Create: `ContosoKBChatbot.spec` (Knowledge Base root)
- Create: `build_chatbot_exe.bat` (Knowledge Base root)

- [ ] **Step 1: Install PyInstaller** (already installed by V2.1; skip if present)

```powershell
scraper\venv\Scripts\python.exe -m pip install "pyinstaller>=6.0"
```

- [ ] **Step 2: Create `ContosoKBChatbot.spec`** with content from **APPENDIX I — ContosoKBChatbot.spec**.

- [ ] **Step 3: Create `build_chatbot_exe.bat`** with content from **APPENDIX I — build_chatbot_exe.bat**.

- [ ] **Step 4: Build the exe** (takes several minutes; bundle is large because of torch)

```powershell
.\build_chatbot_exe.bat
```
Expected final line: `Build complete. Artifact: dist\ContosoKBChatbot.exe`.

- [ ] **Step 5: Verify the artifact**

```powershell
Get-Item dist\ContosoKBChatbot.exe | Select-Object Name, Length
```
Expected: size in the 300–700 MB range. If above 800 MB, report `DONE_WITH_CONCERNS`.

---

## Task 10: User-driven smoke test + handoff

- [ ] **Step 1: Re-run full test suites**

```powershell
scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/ -v
scraper\venv\Scripts\python.exe -m pytest tests/ -v
```
Expected: both green.

- [ ] **Step 2: USER STEP — first-run setup**

Double-click `dist\ContosoKBChatbot.exe`. On first run, paste the Anthropic API key into the Settings dialog (stored in Windows Credential Manager). Confirm library path defaults to `dist\library`.

- [ ] **Step 3: USER STEP — Reindex**

Click **Reindex**. ~1–2 minutes on CPU for 156 versions (~1500–2000 chunks).

- [ ] **Step 4: USER STEP — Smoke questions**

| Question | Expected behaviour |
|---|---|
| `When did IBAN validation get added to SalesHub?` | Answers with `[SalesHub 2.0.2.1 · enhancement · TFS-57196]` citation. |
| `Any fix related to dashboard?` (no product) | Asks a clarifying question if results span products. |
| `What is the weather in Tokyo?` | Abstains. |
| `Compare risk levels across recent SalesHub enhancements` | Cites specific TFS IDs; no hallucination. |

- [ ] **Step 5: USER STEP — Stop button**

Start a broad question; click **Stop**. Reply shows "Cancelled.", window stays open.

- [ ] **Step 6: USER STEP — Inspect logs**

`View logs` opens `dist\chatbot_state\`. Confirm `run.log` has structured entries and `usage.jsonl` has one JSON line per question.

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

# Appendices

## APPENDIX A — Scaffold files

### `Dev/kb_chatbot/config.py`

```python
"""Static defaults + freeze-aware paths. No persisted settings live here."""
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

LIBRARY_DEFAULT = BASE_DIR / "library"
CHROMA_DIR      = STATE_DIR / "chroma"
CHATS_DIR       = STATE_DIR / "chats"
LOG_FILE        = STATE_DIR / "run.log"
USAGE_FILE      = STATE_DIR / "usage.jsonl"
SETTINGS_FILE   = STATE_DIR / "settings.json"

# ── Model defaults ────────────────────────────────────────────────────────────
EMBED_MODEL        = "sentence-transformers/all-MiniLM-L6-v2"
RERANKER_MODEL     = "cross-encoder/ms-marco-MiniLM-L-6-v2"

DEFAULT_MODEL      = "claude-haiku-4-5-20251001"
AVAILABLE_MODELS   = {
    "Haiku (fast / cheap)": "claude-haiku-4-5-20251001",
    "Sonnet (smarter)":     "claude-sonnet-4-6",
}

# ── Retrieval defaults ────────────────────────────────────────────────────────
TOP_K_RETRIEVE     = 30
TOP_K_RERANK       = 8
CONFIDENCE_FLOOR   = 0.30
MAX_HISTORY_TURNS  = 6

# ── Cost estimation (USD per million tokens; review periodically) ────────────
COST_TABLE: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
    "claude-sonnet-4-6":         {"in": 3.00, "out": 15.00},
}

KEYRING_SERVICE    = "kb_chatbot"
KEYRING_USERNAME   = "anthropic"
```

### `Dev/kb_chatbot/settings.py`

```python
"""Persisted settings (JSON) + API key (OS keyring). API key never written to disk."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import keyring

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


def get_api_key() -> Optional[str]:
    return keyring.get_password(config.KEYRING_SERVICE, config.KEYRING_USERNAME) or os.environ.get("ANTHROPIC_API_KEY")


def set_api_key(key: str) -> None:
    keyring.set_password(config.KEYRING_SERVICE, config.KEYRING_USERNAME, key)


def clear_api_key() -> None:
    try:
        keyring.delete_password(config.KEYRING_SERVICE, config.KEYRING_USERNAME)
    except Exception:
        pass
```

### `Dev/kb_chatbot/tests/conftest.py`

```python
# Shared pytest fixtures for kb_chatbot tests.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
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
            library_path=Path("X:/some/library"),
            default_model="claude-sonnet-4-6",
            confidence_floor=0.45,
        )
        save_settings(original, path)
        loaded = load_settings(path)
        assert loaded.library_path == Path("X:/some/library")
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


def test_api_key_uses_keyring(monkeypatch):
    from Dev.kb_chatbot import settings as s_mod
    store: dict = {}
    monkeypatch.setattr(s_mod.keyring, "set_password", lambda svc, u, v: store.update({(svc,u):v}))
    monkeypatch.setattr(s_mod.keyring, "get_password", lambda svc, u: store.get((svc,u)))
    monkeypatch.setattr(s_mod.keyring, "delete_password", lambda svc, u: store.pop((svc,u), None))
    assert s_mod.get_api_key() is None
    s_mod.set_api_key("sk-test-12345")
    assert s_mod.get_api_key() == "sk-test-12345"
    s_mod.clear_api_key()
    assert s_mod.get_api_key() is None
```

---

## APPENDIX B — Tiny library + chunker

### `Dev/kb_chatbot/tests/fixtures/tiny_library/tradedesk/versions/3.0.1.9.json`

```json
{
  "product": "tradedesk",
  "version": "3.0.1.9",
  "title": "Version 3.0.1.9",
  "url": "http://example/tradedesk/3.0.1.9",
  "scraped_at": "2026-05-28T10:00:00",
  "screenshot": "tiny.png",
  "enhancements": [
    {"sno": "1", "id": "14093", "module": "Dashboard Activity",
     "details": "Dashboard Activity query optimization improves load time", "risk": "LOW"}
  ],
  "bugs": [
    {"sno": "1", "id": "14081", "module": "Corporate Dealing",
     "details": "Fix F10 key behaviour on corporate deal screen", "risk": "LOW"}
  ]
}
```

### `Dev/kb_chatbot/tests/fixtures/tiny_library/web4/versions/4.0.3.0.json`

```json
{
  "product": "web4",
  "version": "4.0.3.0",
  "title": "Version 4.0.3.0",
  "url": "http://example/web4/4.0.3.0",
  "scraped_at": "2026-05-28T10:00:00",
  "screenshot": "tiny.png",
  "tasks": [
    {"sno": "1", "id": "71669", "details": "Quick Pay and Payment Links new feature",
     "key_feature": "NO", "behavior_change": "NO", "risk": "LOW"}
  ]
}
```

### `Dev/kb_chatbot/tests/fixtures/tiny_library/saleshub/versions/2.0.2.1.json`

```json
{
  "product": "saleshub",
  "version": "2.0.2.1",
  "title": "SalesHub WEB Version 2.0.2.1",
  "url": "http://example/saleshub/2.0.2.1",
  "scraped_at": "2026-05-28T10:00:00",
  "screenshot": "tiny.png",
  "enhancements": [
    {"sno": "1", "id": "57196", "details": "IBAN Validation and Look-up enhancement",
     "config_changes": "NO", "key_feature": "YES", "risk": "LOW"}
  ],
  "schema_changes": [
    {"object_type": "Table", "object_name": "WEB_FTF_DETAIL", "action_type": "Altered"}
  ]
}
```

### `Dev/kb_chatbot/tests/test_chunker.py`

```python
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chunker import build_row_chunks, build_version_chunk, Chunk

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def _load(product: str, version: str) -> dict:
    return json.loads((FIX / product / "versions" / f"{version}.json").read_text(encoding="utf-8"))


def test_row_chunks_one_per_row():
    data = _load("tradedesk", "3.0.1.9")
    chunks = build_row_chunks(data)
    assert len(chunks) == 2  # 1 enhancement + 1 bug

def test_row_chunk_id_format():
    data = _load("tradedesk", "3.0.1.9")
    chunks = build_row_chunks(data)
    ids = {c.id for c in chunks}
    assert "tradedesk/3.0.1.9/enhancements/0" in ids
    assert "tradedesk/3.0.1.9/bugs/0" in ids

def test_row_chunk_metadata():
    data = _load("saleshub", "2.0.2.1")
    chunks = build_row_chunks(data)
    enh = next(c for c in chunks if c.metadata["section"] == "enhancements")
    assert enh.metadata["product"] == "saleshub"
    assert enh.metadata["version"] == "2.0.2.1"
    assert enh.metadata["row_id"] == "57196"
    assert enh.metadata["kind"] == "row"
    assert enh.metadata["url"] == "http://example/saleshub/2.0.2.1"

def test_row_chunk_text_includes_key_fields():
    data = _load("saleshub", "2.0.2.1")
    chunks = build_row_chunks(data)
    enh_text = next(c.text for c in chunks if c.metadata["section"] == "enhancements")
    assert "57196" in enh_text
    assert "IBAN" in enh_text
    assert "saleshub" in enh_text.lower()
    assert "2.0.2.1" in enh_text

def test_schema_change_row_without_id_still_chunked():
    data = _load("saleshub", "2.0.2.1")
    chunks = build_row_chunks(data)
    schema = [c for c in chunks if c.metadata["section"] == "schema_changes"]
    assert len(schema) == 1
    assert "WEB_FTF_DETAIL" in schema[0].text
    assert schema[0].metadata["row_id"] == ""

def test_version_chunk_summary():
    data = _load("tradedesk", "3.0.1.9")
    v = build_version_chunk(data)
    assert isinstance(v, Chunk)
    assert v.metadata["kind"] == "version"
    assert v.metadata["product"] == "tradedesk"
    assert "3.0.1.9" in v.text
    assert "enhancements" in v.text.lower()
    assert "bugs" in v.text.lower()

def test_web4_tasks_section_supported():
    data = _load("web4", "4.0.3.0")
    chunks = build_row_chunks(data)
    assert any(c.metadata["section"] == "tasks" for c in chunks)
    t = next(c for c in chunks if c.metadata["section"] == "tasks")
    assert t.metadata["row_id"] == "71669"
    assert "Quick Pay" in t.text
```

### `Dev/kb_chatbot/chunker.py`

```python
"""Builds Chunk objects from a version JSON. Pure functions; no IO."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

ROW_SECTIONS = ("enhancements", "bugs", "tasks", "schema_changes")


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _row_text(product: str, version: str, section: str, row: dict) -> str:
    parts = [f"{product} {version} {section}"]
    if row.get("id"):
        parts.append(f"ID {row['id']}")
    pieces = []
    for k, v in row.items():
        if k == "id" or not v:
            continue
        pieces.append(f"{k.replace('_',' ')}: {v}")
    if pieces:
        parts.append(" | ".join(pieces))
    return "  ".join(parts)


def _md_path_for(product: str, version: str) -> str:
    safe = version.replace(" ", "_").replace("/", "-").strip()
    return f"library/{product}/versions/{safe}.md"


def build_row_chunks(version_data: dict) -> list[Chunk]:
    product = version_data["product"]
    version = version_data["version"]
    url     = version_data.get("url", "")
    md_path = _md_path_for(product, version)
    out: list[Chunk] = []
    for section in ROW_SECTIONS:
        rows = version_data.get(section, [])
        for idx, row in enumerate(rows):
            chunk_id = f"{product}/{version}/{section}/{idx}"
            out.append(Chunk(
                id=chunk_id,
                text=_row_text(product, version, section, row),
                metadata={
                    "kind": "row",
                    "product": product,
                    "version": version,
                    "section": section,
                    "row_id": str(row.get("id", "")),
                    "title": version_data.get("title", ""),
                    "url": url,
                    "md_path": md_path,
                },
            ))
    return out


def build_version_chunk(version_data: dict) -> Chunk:
    product = version_data["product"]
    version = version_data["version"]
    title   = version_data.get("title", f"Version {version}")
    section_counts = {s: len(version_data.get(s, [])) for s in ROW_SECTIONS if version_data.get(s)}
    summary = ", ".join(f"{n} {sec}" for sec, n in section_counts.items()) or "no items"
    text = f"{product} {version} — {title}.  Contains {summary}."
    return Chunk(
        id=f"{product}/{version}/__version__",
        text=text,
        metadata={
            "kind": "version",
            "product": product,
            "version": version,
            "section": "",
            "row_id": "",
            "title": title,
            "url": version_data.get("url", ""),
            "md_path": _md_path_for(product, version),
        },
    )
```

---

## APPENDIX C — Ingest

### `Dev/kb_chatbot/tests/test_ingest.py`

```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.ingest import ingest

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def test_ingest_reports_correct_counts():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert report.versions_seen == 3
        # tradedesk(2) + web4(1) + saleshub(2) = 5 rows + 3 version chunks = 8
        assert report.chunks_created == 8


def test_ingest_creates_chroma_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        files = list(Path(tmp).rglob("*"))
        assert any(p.suffix == ".sqlite3" for p in files) or any(p.is_dir() for p in files)


def test_ingest_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        r1 = ingest(FIX, Path(tmp))
        r2 = ingest(FIX, Path(tmp))
        assert r1.chunks_created == r2.chunks_created


def test_ingest_returns_per_product_counts():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert report.products == {"tradedesk": 1, "web4": 1, "saleshub": 1}


def test_ingest_collection_queryable_after_ingest():
    import chromadb
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        client = chromadb.PersistentClient(path=str(tmp))
        coll = client.get_collection("kb")
        all_records = coll.get()
        assert len(all_records["ids"]) >= 8
        products = {m["product"] for m in all_records["metadatas"]}
        assert products == {"tradedesk", "web4", "saleshub"}
```

### `Dev/kb_chatbot/ingest.py`

```python
"""Walks a library/ dir, builds chunks, embeds them, persists to ChromaDB."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import chromadb
from sentence_transformers import SentenceTransformer

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import build_row_chunks, build_version_chunk, Chunk

log = logging.getLogger("kb_chatbot.ingest")

COLLECTION_NAME = "kb"
BATCH_SIZE = 64


@dataclass
class IngestReport:
    versions_seen: int = 0
    chunks_created: int = 0
    products: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0


def _gather_version_jsons(library_path: Path) -> list[Path]:
    return sorted(library_path.glob("*/versions/*.json"))


def _embed_batch(model: SentenceTransformer, texts: list[str]) -> list[list[float]]:
    vecs = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def ingest(
    library_path: Path,
    chroma_path: Path,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
) -> IngestReport:
    import time
    started = time.time()

    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    embedder = SentenceTransformer(config.EMBED_MODEL)

    files = _gather_version_jsons(library_path)
    report = IngestReport()
    all_chunks: list[Chunk] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Skipping %s: %s", f, exc)
            continue
        product = data.get("product", "unknown")
        report.versions_seen += 1
        report.products[product] = report.products.get(product, 0) + 1
        all_chunks.extend(build_row_chunks(data))
        all_chunks.append(build_version_chunk(data))

    total = len(all_chunks)
    if total == 0:
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
    log.info("Ingest: %d versions, %d chunks, %.1fs", report.versions_seen, report.chunks_created, report.duration_s)
    return report
```

---

## APPENDIX D — Retriever

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


def test_retrieve_returns_chunks(retriever):
    r = retriever.retrieve("IBAN validation", Filters())
    assert isinstance(r, RetrievalResult)
    assert len(r.chunks) > 0
    assert r.chunks[0].metadata["product"] == "saleshub"


def test_filter_by_product(retriever):
    r = retriever.retrieve("anything", Filters(product="tradedesk"))
    assert all(c.metadata["product"] == "tradedesk" for c in r.chunks)


def test_retrieve_returns_top_k_max(retriever):
    r = retriever.retrieve("dashboard", Filters())
    assert len(r.chunks) <= retriever.top_k_rerank


def test_retrieve_quick_returns_top_k_no_rerank(retriever):
    r = retriever.retrieve_quick("payment", limit=5)
    assert len(r) <= 5
    assert all("product" in c.metadata for c in r)


def test_confidence_gate_triggers_for_unrelated_query():
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        strict = Retriever(Path(tmp), confidence_floor=0.99)
        r = strict.retrieve("quantum field theory", Filters())
        assert r.abstain_reason == "no_relevant_kb_match"
        assert r.chunks == []
```

### `Dev/kb_chatbot/retriever.py`

```python
"""Embed query, vector-search ChromaDB, rerank, confidence-gate."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.ingest import COLLECTION_NAME

log = logging.getLogger("kb_chatbot.retriever")


@dataclass
class Filters:
    product: Optional[str] = None
    version_min: Optional[str] = None
    version_max: Optional[str] = None


@dataclass
class RetrievalResult:
    chunks: list[Chunk] = field(default_factory=list)
    raw_top_score: float = 0.0
    rerank_top_score: float = 0.0
    abstain_reason: Optional[str] = None


class Retriever:
    def __init__(
        self,
        chroma_path: Path,
        *,
        top_k_retrieve: int = config.TOP_K_RETRIEVE,
        top_k_rerank: int = config.TOP_K_RERANK,
        confidence_floor: float = config.CONFIDENCE_FLOOR,
    ):
        self.client = chromadb.PersistentClient(path=str(chroma_path))
        self.collection = self.client.get_or_create_collection(name=COLLECTION_NAME)
        self.embedder = SentenceTransformer(config.EMBED_MODEL)
        self.reranker = CrossEncoder(config.RERANKER_MODEL)
        self.top_k_retrieve = top_k_retrieve
        self.top_k_rerank = top_k_rerank
        self.confidence_floor = confidence_floor

    def _embed(self, text: str) -> list[float]:
        return self.embedder.encode(text, convert_to_numpy=True).tolist()

    def _query_chroma(self, query_vec: list[float], filters: Filters, n_results: int) -> list[Chunk]:
        where: dict = {}
        if filters.product:
            where["product"] = filters.product
        results = self.collection.query(
            query_embeddings=[query_vec],
            n_results=n_results,
            where=where or None,
        )
        chunks: list[Chunk] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        for cid, doc, meta in zip(ids, docs, metas):
            chunks.append(Chunk(id=cid, text=doc, metadata=dict(meta or {})))
        return chunks

    def retrieve(self, query: str, filters: Filters) -> RetrievalResult:
        query_vec = self._embed(query)
        candidates = self._query_chroma(query_vec, filters, self.top_k_retrieve)
        if not candidates:
            return RetrievalResult(abstain_reason="no_relevant_kb_match")

        pairs = [(query, c.text) for c in candidates]
        scores = self.reranker.predict(pairs)
        scored = sorted(zip(candidates, scores), key=lambda t: t[1], reverse=True)
        top = scored[: self.top_k_rerank]
        top_score = float(top[0][1]) if top else 0.0

        if top_score < self.confidence_floor:
            log.info("Abstaining: top rerank score %.3f < floor %.3f", top_score, self.confidence_floor)
            return RetrievalResult(
                chunks=[],
                raw_top_score=0.0,
                rerank_top_score=top_score,
                abstain_reason="no_relevant_kb_match",
            )

        return RetrievalResult(
            chunks=[c for c, _ in top],
            raw_top_score=0.0,
            rerank_top_score=top_score,
        )

    def retrieve_quick(self, query: str, limit: int = 10) -> list[Chunk]:
        query_vec = self._embed(query)
        return self._query_chroma(query_vec, Filters(), limit)
```

---

## APPENDIX E — Prompt + citations

### `Dev/kb_chatbot/tests/test_prompt.py`

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.prompt import SYSTEM_PROMPT, build_system_prompt, format_context, build_messages
from Dev.kb_chatbot.chunker import Chunk


def test_system_prompt_is_locked_text():
    p = build_system_prompt()
    assert p == SYSTEM_PROMPT
    assert "may only use facts from the CONTEXT block" in p
    assert "I don't have a record of this in the knowledge base" in p
    assert "[<Product> <Version> · <section> · <ID>]" in p


def test_format_context_renders_chunks_with_cite_handles():
    chunks = [
        Chunk(id="saleshub/2.0.2.1/enhancements/0",
              text="saleshub 2.0.2.1 enhancements ID 57196  IBAN Validation",
              metadata={"product":"saleshub","version":"2.0.2.1","section":"enhancements","row_id":"57196"}),
    ]
    out = format_context(chunks)
    assert "IBAN Validation" in out
    assert "[SalesHub 2.0.2.1 · enhancement · TFS-57196]" in out


def test_build_messages_shape():
    chunks = [
        Chunk(id="x", text="hello", metadata={"product":"web4","version":"4.0.3.0","section":"tasks","row_id":"71669"}),
    ]
    msgs = build_messages(context_chunks=chunks, history=[], user_msg="When?")
    assert msgs[-1]["role"] == "user"
    assert "When?" in msgs[-1]["content"]
    assert "[Web4 4.0.3.0 · tasks · TFS-71669]" in msgs[-1]["content"]


def test_build_messages_includes_history():
    chunks = []
    history = [
        {"role": "user", "content": "Earlier question?"},
        {"role": "assistant", "content": "Earlier answer."},
    ]
    msgs = build_messages(context_chunks=chunks, history=history, user_msg="Now?")
    assert msgs[0]["content"] == "Earlier question?"
    assert msgs[1]["content"] == "Earlier answer."
    assert "Now?" in msgs[-1]["content"]
```

### `Dev/kb_chatbot/prompt.py`

```python
"""Locked system prompt + context formatter + Anthropic message builder."""
from __future__ import annotations
from Dev.kb_chatbot.chunker import Chunk

_SECTION_SINGULAR = {
    "enhancements": "enhancement",
    "bugs": "bug",
    "tasks": "tasks",
    "schema_changes": "schema_change",
}

_PRODUCT_DISPLAY = {"tradedesk": "TradeDesk", "web4": "Web4", "saleshub": "SalesHub"}


SYSTEM_PROMPT = """You are the Contoso Knowledge Base Assistant. You answer questions about the TradeDesk, Web4, and SalesHub release notes — and only the release notes.

Hard rules — no exceptions:
1. You may only use facts from the CONTEXT block below. You have no other knowledge of Contoso products. Do not use general knowledge, intuition, or assumptions.
2. If the answer is not in the context, reply exactly: "I don't have a record of this in the knowledge base. Want to refine the question?" — and offer one specific refinement (different product, broader version range, related keyword). Never invent.
3. Every factual claim must end with a citation tag in this exact form: [<Product> <Version> · <section> · <ID>] — e.g. [SalesHub 2.0.2.1 · enhancement · TFS-57196]. A claim without a valid citation is forbidden.
4. If the user's intent is ambiguous (could refer to multiple products, a too-broad version range, or a vague feature name), do not answer. Instead, ask exactly one clarifying question.
5. Format the answer as: one-sentence direct answer first; then bullet list of relevant items (each with citation); then a "Searched:" footnote naming the product(s) and version range you considered.

Do not editorialise. Do not apologise. Do not speculate about future versions. Do not summarise sections that weren't retrieved."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def _cite_handle(meta: dict) -> str:
    product = _PRODUCT_DISPLAY.get(meta.get("product", ""), meta.get("product", ""))
    section = _SECTION_SINGULAR.get(meta.get("section", ""), meta.get("section", ""))
    row_id = meta.get("row_id", "")
    return f"[{product} {meta.get('version','')} · {section} · TFS-{row_id}]"


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

### `Dev/kb_chatbot/tests/test_citations.py`

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.citations import parse_citations, validate, Citation
from Dev.kb_chatbot.chunker import Chunk


def _chunk(product, version, section, row_id):
    return Chunk(id=f"{product}/{version}/{section}/0", text="...",
                 metadata={"product": product, "version": version,
                           "section": section, "row_id": row_id, "kind": "row"})


def test_parses_well_formed_citation():
    txt = "Some claim [SalesHub 2.0.2.1 · enhancement · TFS-57196]."
    cites = parse_citations(txt)
    assert len(cites) == 1
    c = cites[0]
    assert c.product == "SalesHub"
    assert c.version == "2.0.2.1"
    assert c.section == "enhancement"
    assert c.row_id == "57196"


def test_parses_multiple_citations():
    txt = "Claim A [TradeDesk 3.0.1.9 · enhancement · TFS-14093]. Claim B [Web4 4.0.3.0 · tasks · TFS-71669]."
    cites = parse_citations(txt)
    assert len(cites) == 2


def test_ignores_malformed_citation():
    txt = "Loose mention [SalesHub 2.0.2.1 · enhancement · 57196]."
    cites = parse_citations(txt)
    assert cites == []


def test_validator_accepts_matching_citation():
    retrieved = [_chunk("saleshub", "2.0.2.1", "enhancements", "57196")]
    answer = "X [SalesHub 2.0.2.1 · enhancement · TFS-57196]."
    result = validate(answer, retrieved)
    assert result.all_verified is True
    assert result.stripped_text == answer


def test_validator_strips_hallucinated_citation():
    retrieved = [_chunk("saleshub", "2.0.2.1", "enhancements", "57196")]
    answer = "X [TradeDesk 9.9.9.9 · enhancement · TFS-99999]."
    result = validate(answer, retrieved)
    assert result.all_verified is False
    assert "[unverified]" in result.stripped_text
    assert "TFS-99999" not in result.stripped_text
    assert len(result.unverified) == 1


def test_section_singular_vs_plural_matches():
    retrieved = [_chunk("saleshub", "2.0.2.1", "enhancements", "57196")]
    answer = "X [SalesHub 2.0.2.1 · enhancement · TFS-57196]."
    result = validate(answer, retrieved)
    assert result.all_verified is True
```

### `Dev/kb_chatbot/citations.py`

```python
"""Parse + validate the locked citation form: [<Product> <Version> · <section> · TFS-<ID>]."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import List

from Dev.kb_chatbot.chunker import Chunk

log = logging.getLogger("kb_chatbot.citations")

_CITE_RE = re.compile(
    r"\["
    r"(?P<product>TradeDesk|Web4|SalesHub)\s+"
    r"(?P<version>\d+(?:\.\d+){2,})\s+·\s+"
    r"(?P<section>enhancement|enhancements|bug|bugs|task|tasks|schema_change|schema_changes)\s+·\s+"
    r"TFS-(?P<row_id>\d+)"
    r"\]"
)

_PRODUCT_NORMAL = {"TradeDesk": "tradedesk", "Web4": "web4", "SalesHub": "saleshub"}
_SECTION_PLURAL = {
    "enhancement": "enhancements", "enhancements": "enhancements",
    "bug": "bugs", "bugs": "bugs",
    "task": "tasks", "tasks": "tasks",
    "schema_change": "schema_changes", "schema_changes": "schema_changes",
}


@dataclass
class Citation:
    raw: str
    product: str
    version: str
    section: str
    row_id: str


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
            version=m.group("version"),
            section=m.group("section"),
            row_id=m.group("row_id"),
        ))
    return out


def _matches(cite: Citation, chunk: Chunk) -> bool:
    md = chunk.metadata
    return (
        _PRODUCT_NORMAL.get(cite.product) == md.get("product")
        and cite.version == md.get("version")
        and _SECTION_PLURAL.get(cite.section) == md.get("section")
        and cite.row_id == md.get("row_id")
    )


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

---

## APPENDIX F — LLM provider

### `Dev/kb_chatbot/tests/test_llm.py`

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.llm.base import LLMResponse, LLMProvider
from Dev.kb_chatbot.llm.fake_provider import FakeProvider


def test_fake_provider_returns_canned_text():
    fp = FakeProvider(canned_text="hello world", input_tokens=10, output_tokens=5)
    r = fp.chat(messages=[{"role": "user", "content": "ignored"}],
                model="claude-haiku-4-5-20251001",
                system_prompt="sys")
    assert isinstance(r, LLMResponse)
    assert r.text == "hello world"
    assert r.input_tokens == 10
    assert r.output_tokens == 5
    assert r.cost_estimate_usd > 0


def test_fake_provider_cost_is_nonnegative_for_unknown_model():
    fp = FakeProvider(canned_text="x")
    r = fp.chat(messages=[{"role": "user", "content": "x"}],
                model="some-future-model",
                system_prompt="sys")
    assert r.cost_estimate_usd >= 0.0


def test_base_provider_is_abstract():
    import pytest
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]
```

### `Dev/kb_chatbot/llm/base.py`

```python
"""Abstract LLM provider + shared cost-estimate helper."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

from Dev.kb_chatbot import config


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: int
    cost_estimate_usd: float


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = config.COST_TABLE.get(model, {"in": 0.0, "out": 0.0})
    return (input_tokens / 1_000_000 * price["in"]) + (output_tokens / 1_000_000 * price["out"])


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, *, messages: list[dict], model: str, system_prompt: str,
             max_tokens: int = 1024) -> LLMResponse: ...
```

### `Dev/kb_chatbot/llm/fake_provider.py`

```python
"""Deterministic provider for tests; never touches the network."""
from __future__ import annotations
from Dev.kb_chatbot.llm.base import LLMProvider, LLMResponse, estimate_cost


class FakeProvider(LLMProvider):
    def __init__(self, canned_text: str = "(fake response)",
                 input_tokens: int = 100, output_tokens: int = 50,
                 latency_ms: int = 1):
        self.canned_text = canned_text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms
        self.calls: list[dict] = []

    def chat(self, *, messages, model, system_prompt, max_tokens=1024) -> LLMResponse:
        self.calls.append({"messages": messages, "model": model,
                           "system_prompt": system_prompt, "max_tokens": max_tokens})
        return LLMResponse(
            text=self.canned_text,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model=model,
            latency_ms=self.latency_ms,
            cost_estimate_usd=estimate_cost(model, self.input_tokens, self.output_tokens),
        )
```

### `Dev/kb_chatbot/llm/anthropic_provider.py`

```python
"""Anthropic implementation using the official SDK."""
from __future__ import annotations
import logging
import time

from anthropic import Anthropic, APIError

from Dev.kb_chatbot.llm.base import LLMProvider, LLMResponse, estimate_cost

log = logging.getLogger("kb_chatbot.llm.anthropic")


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Anthropic API key is required")
        self.client = Anthropic(api_key=api_key)

    def chat(self, *, messages, model, system_prompt, max_tokens=1024) -> LLMResponse:
        started = time.time()
        try:
            resp = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )
        except APIError as exc:
            log.error("Anthropic API error: %s", exc)
            raise
        latency_ms = int((time.time() - started) * 1000)
        text = "".join(getattr(block, "text", "") for block in resp.content)
        return LLMResponse(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=model,
            latency_ms=latency_ms,
            cost_estimate_usd=estimate_cost(model, resp.usage.input_tokens, resp.usage.output_tokens),
        )
```

---

## APPENDIX G — Session + orchestrator + golden Q&A

### `Dev/kb_chatbot/tests/fixtures/golden_qa.json`

```json
[
  {
    "name": "iban_in_saleshub_clear",
    "user_msg": "Does SalesHub have IBAN validation?",
    "filters": {},
    "expect": "answer",
    "must_retrieve_any_of": ["saleshub/2.0.2.1/enhancements/0"]
  },
  {
    "name": "f10_key_in_tradedesk",
    "user_msg": "Tell me about the F10 key fix in TradeDesk",
    "filters": {},
    "expect": "answer",
    "must_retrieve_any_of": ["tradedesk/3.0.1.9/bugs/0"]
  },
  {
    "name": "quick_pay_in_web4",
    "user_msg": "When did Web4 get Quick Pay?",
    "filters": {},
    "expect": "answer",
    "must_retrieve_any_of": ["web4/4.0.3.0/tasks/0"]
  },
  {
    "name": "iban_no_product_named_should_clarify",
    "user_msg": "Where is IBAN validation handled?",
    "filters": {},
    "expect": "answer",
    "must_retrieve_any_of": ["saleshub/2.0.2.1/enhancements/0"]
  },
  {
    "name": "off_topic_abstain",
    "user_msg": "What is the meaning of life?",
    "filters": {},
    "expect": "abstain"
  }
]
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
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def deps():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))
    retriever = Retriever(Path(tmp), confidence_floor=0.0)
    return Retriever, retriever, tmp


def _make_deps(retriever, fake_text="Answer [SalesHub 2.0.2.1 · enhancement · TFS-57196]."):
    llm = FakeProvider(canned_text=fake_text, input_tokens=50, output_tokens=20)
    return Deps(retriever=retriever, llm=llm,
                usage_logger=lambda turn: None,
                clarifier=None), llm


def test_clear_question_yields_answer_turn(deps):
    _, retriever, _ = deps
    d, _ = _make_deps(retriever)
    session = Session.new()
    turn = handle_turn("Tell me about IBAN validation in SalesHub", session,
                       Filters(product="saleshub"), default_model="claude-haiku-4-5-20251001",
                       deps=d)
    assert turn.role == "assistant"
    assert turn.kind == "answer"
    assert "TFS-57196" in turn.content


def test_ambiguous_question_yields_clarification(deps):
    _, retriever, _ = deps
    d, fake = _make_deps(retriever)
    session = Session.new()
    turn = handle_turn("any fix?", session, Filters(), "claude-haiku-4-5-20251001", deps=d)
    if turn.kind == "clarification":
        assert len(fake.calls) == 0


def test_abstain_when_retrieval_below_floor():
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        strict = Retriever(Path(tmp), confidence_floor=0.99)
        d, fake = _make_deps(strict)
        session = Session.new()
        turn = handle_turn("quantum gravity", session, Filters(), "claude-haiku-4-5-20251001", deps=d)
        assert turn.kind == "abstain"
        assert len(fake.calls) == 0


def test_hallucinated_citation_gets_stripped(deps):
    _, retriever, _ = deps
    d, _ = _make_deps(retriever,
                       fake_text="Hallucinated [SalesHub 9.9.9.9 · enhancement · TFS-99999].")
    session = Session.new()
    turn = handle_turn("IBAN in saleshub", session,
                        Filters(product="saleshub"), "claude-haiku-4-5-20251001", deps=d)
    assert "[unverified]" in turn.content
    assert "TFS-99999" not in turn.content


def test_session_persists_turns():
    s = Session.new()
    assert s.turns == []
    s.add_user("hello")
    assert s.turns[-1]["role"] == "user"
```

### `Dev/kb_chatbot/chat/session.py`

```python
"""Per-conversation state. Serialisable. No I/O at import time."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4


@dataclass
class Turn:
    role: str
    content: str
    kind: str = "answer"
    citations: list[dict] = field(default_factory=list)
    retrieved_ids: list[str] = field(default_factory=list)
    model: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    ts: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Session:
    id: str
    turns: list[dict] = field(default_factory=list)

    @classmethod
    def new(cls) -> "Session":
        return cls(id=datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:4])

    def add_user(self, msg: str) -> None:
        self.turns.append(Turn(role="user", content=msg, kind="user").to_dict())

    def add(self, turn: Turn) -> None:
        self.turns.append(turn.to_dict())

    def history_for_llm(self, max_turns: int = 6) -> list[dict]:
        kept = self.turns[-max_turns * 2 :] if max_turns > 0 else []
        return [{"role": t["role"], "content": t["content"]} for t in kept if t["role"] in ("user", "assistant")]

    def save(self, dir_path: Path) -> Path:
        dir_path.mkdir(parents=True, exist_ok=True)
        path = dir_path / f"{self.id}.json"
        path.write_text(json.dumps({"id": self.id, "turns": self.turns}, indent=2), encoding="utf-8")
        return path
```

### `Dev/kb_chatbot/chat/orchestrator.py`

```python
"""Per-turn pipeline: ambiguity → retrieve → gate → prompt → LLM → validate."""
from __future__ import annotations
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.citations import validate as validate_citations
from Dev.kb_chatbot.llm.base import LLMProvider
from Dev.kb_chatbot.prompt import build_system_prompt, build_messages
from Dev.kb_chatbot.retriever import Retriever, Filters

log = logging.getLogger("kb_chatbot.orchestrator")

PRODUCTS = ("tradedesk", "web4", "saleshub")


@dataclass
class Deps:
    retriever: Retriever
    llm: LLMProvider
    usage_logger: Callable[[Turn], None] = lambda t: None
    clarifier: Optional[Callable[[str, list[Chunk]], str]] = None


def _mentions_product(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in PRODUCTS)


def _recent_product_in_history(session: Session) -> bool:
    for t in reversed(session.turns[-6:]):
        if _mentions_product(t["content"]):
            return True
    return False


def _needs_clarification(user_msg: str, session: Session, filters: Filters,
                         retriever: Retriever) -> Optional[list[Chunk]]:
    if filters.product or _mentions_product(user_msg) or _recent_product_in_history(session):
        return None
    quick = retriever.retrieve_quick(user_msg, limit=10)
    if not quick:
        return None
    products = Counter(c.metadata.get("product", "") for c in quick)
    if len(products) <= 1:
        return None
    total = sum(products.values())
    dominant = products.most_common(1)[0][1]
    if dominant / total >= 0.60:
        return None
    return quick


def _default_clarifier(user_msg: str, quick: list[Chunk]) -> str:
    products = sorted({c.metadata.get("product", "") for c in quick if c.metadata.get("product")})
    pretty = ", ".join(p.title() if p != "saleshub" else "SalesHub" for p in products) or "TradeDesk, Web4, or SalesHub"
    return (f"Multiple products have records that look related to your question. "
            f"Which one are you asking about — {pretty}?")


def handle_turn(user_msg: str, session: Session, filters: Filters,
                default_model: str, *, deps: Deps) -> Turn:
    session.add_user(user_msg)

    quick = _needs_clarification(user_msg, session, filters, deps.retriever)
    if quick is not None:
        clar_fn = deps.clarifier or _default_clarifier
        msg = clar_fn(user_msg, quick)
        turn = Turn(role="assistant", content=msg, kind="clarification",
                    retrieved_ids=[c.id for c in quick])
        session.add(turn)
        deps.usage_logger(turn)
        return turn

    result = deps.retriever.retrieve(user_msg, filters)
    if result.abstain_reason:
        turn = Turn(role="assistant",
                    content=("I don't have a record of this in the knowledge base. "
                             "Want to refine the question? Try naming a product, a version range, "
                             "or a more specific keyword."),
                    kind="abstain")
        session.add(turn)
        deps.usage_logger(turn)
        return turn

    messages = build_messages(
        context_chunks=result.chunks,
        history=session.history_for_llm(config.MAX_HISTORY_TURNS),
        user_msg=user_msg,
    )
    started = time.time()
    try:
        resp = deps.llm.chat(
            messages=messages,
            model=default_model,
            system_prompt=build_system_prompt(),
            max_tokens=1024,
        )
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
    must_any = case.get("must_retrieve_any_of", [])
    fake_cite = ""
    if must_any:
        product, version, section, idx = must_any[0].split("/")
        plain = {"enhancements": "enhancement", "bugs": "bug", "tasks": "tasks", "schema_changes": "schema_change"}[section]
        prod_display = {"tradedesk": "TradeDesk", "web4": "Web4", "saleshub": "SalesHub"}[product]
        fake_cite = f"[{prod_display} {version} · {plain} · TFS-99999]"

    deps = deps_factory(confidence_floor=0.0, fake_text=f"Stub answer {fake_cite}")
    if case["expect"] == "abstain":
        deps = deps_factory(confidence_floor=0.99, fake_text="should never see this")

    session = Session.new()
    filters = Filters(**case.get("filters", {}))
    turn = handle_turn(case["user_msg"], session, filters,
                        "claude-haiku-4-5-20251001", deps=deps)

    if case["expect"] == "abstain":
        assert turn.kind == "abstain"
    else:
        assert turn.kind in ("answer", "clarification")
        if turn.kind == "answer" and must_any:
            assert any(rid in turn.retrieved_ids for rid in must_any)
```

---

## APPENDIX H — GUI

### `Dev/kb_chatbot/gui.py`

```python
"""KB Chatbot GUI. Run from source: scraper\\venv\\Scripts\\python.exe Dev\\kb_chatbot\\gui.py
Packaged as ContosoKBChatbot.exe via PyInstaller."""
from __future__ import annotations
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
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
from Dev.kb_chatbot.llm.anthropic_provider import AnthropicProvider
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
    log = Signal(str)


class TurnWorker(QThread):
    def __init__(self, user_msg: str, session: Session, filters: Filters,
                 default_model: str, deps: Deps):
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


class IngestWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, library_path: Path, chroma_path: Path):
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
    def __init__(self, parent, current: settings_mod.Settings, current_key: Optional[str]):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 220)
        form = QFormLayout(self)
        self.key_edit = QLineEdit(current_key or "")
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-ant-…  (stored in Windows Credential Manager)")
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
        form.addRow("Anthropic API key:", self.key_edit)
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
        return (
            settings_mod.Settings(
                library_path=Path(self.lib_edit.text()),
                default_model=self.model_box.currentData(),
                confidence_floor=config.CONFIDENCE_FLOOR,
            ),
            self.key_edit.text().strip() or None,
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contoso KB Chatbot")
        self.resize(1100, 780)
        self.settings = settings_mod.load_settings()
        self.api_key = settings_mod.get_api_key()
        self.session = Session.new()
        self.worker: Optional[TurnWorker] = None
        self.ingest_worker: Optional[IngestWorker] = None
        self._today_queries = 0
        self._today_tokens = 0

        self._build_ui()
        self._on_settings_changed()

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        tb = QToolBar(); tb.setMovable(False); self.addToolBar(tb)
        act_reindex = QAction("Reindex", self); tb.addAction(act_reindex)
        act_settings = QAction("Settings", self); tb.addAction(act_settings)
        act_clear = QAction("Clear chat", self); tb.addAction(act_clear)
        tb.addSeparator()
        act_stop = QAction("⏹ STOP", self); tb.addAction(act_stop)
        act_logs = QAction("View logs", self); tb.addAction(act_logs)
        self._act_reindex, self._act_settings, self._act_clear = act_reindex, act_settings, act_clear
        self._act_stop, self._act_logs = act_stop, act_logs

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Product:"))
        self.product_box = QComboBox()
        self.product_box.addItem("Any", "")
        for p in ("tradedesk", "web4", "saleshub"):
            self.product_box.addItem(p.title() if p != "saleshub" else "SalesHub", p)
        filter_row.addWidget(self.product_box)
        filter_row.addWidget(QLabel("Model:"))
        self.model_box = QComboBox()
        for label, ident in config.AVAILABLE_MODELS.items():
            self.model_box.addItem(label, ident)
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
        self.input.setPlaceholderText("Ask a question about TradeDesk, Web4, or SalesHub release notes…")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input); input_row.addWidget(self.send_btn)
        outer.addLayout(input_row)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Log: {config.LOG_FILE}")

        act_reindex.triggered.connect(self._reindex)
        act_settings.triggered.connect(self._open_settings)
        act_clear.triggered.connect(self._clear_chat)
        act_stop.triggered.connect(self._stop)
        act_logs.triggered.connect(self._open_logs)

    def _on_settings_changed(self):
        idx = self.model_box.findData(self.settings.default_model)
        if idx >= 0:
            self.model_box.setCurrentIndex(idx)
        if not self.api_key:
            QMessageBox.information(self, "First-run setup",
                "Please paste your Anthropic API key in Settings to begin.")

    def _append_chat(self, role: str, text: str, *, colour: str = "#212121", tag: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat(); fmt.setForeground(QColor(colour))
        cursor.movePosition(QTextCursor.End)
        header = f"{ts} {tag or role.upper():9s} "
        cursor.insertText(header + text + "\n\n", fmt)
        self.chat_view.setTextCursor(cursor)
        self.chat_view.ensureCursorVisible()

    def _send(self):
        msg = self.input.text().strip()
        if not msg or self.worker:
            return
        if not self.api_key:
            self._append_chat("system", "Please set your Anthropic API key in Settings first.", colour="#c62828")
            return

        self.input.clear()
        self._set_inputs_enabled(False)
        self._append_chat("user", msg, colour="#0d47a1", tag="YOU:")

        try:
            llm = AnthropicProvider(api_key=self.api_key)
            retriever = Retriever(config.CHROMA_DIR, confidence_floor=self.settings.confidence_floor)
        except Exception as exc:
            self._append_chat("system", f"Failed to initialise: {exc}", colour="#c62828")
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
    def _on_turn_done(self, turn: Turn):
        if turn.kind == "abstain":
            self._append_chat("ai", turn.content, colour="#5d4037", tag="ABSTAIN:")
        elif turn.kind == "clarification":
            self._append_chat("ai", turn.content, colour="#ef6c00", tag="CLARIFY:")
        else:
            self._append_chat("ai", turn.content, colour="#212121", tag="AI:")
        self._today_queries += 1
        self._today_tokens += turn.tokens_in + turn.tokens_out
        self.statusBar().showMessage(
            f"Today: {self._today_queries} queries · {self._today_tokens} tokens · Log: {config.LOG_FILE}"
        )
        self.worker = None
        self._set_inputs_enabled(True)

    @Slot(str)
    def _on_turn_failed(self, err: str):
        self._append_chat("system", f"Error: {err}", colour="#c62828", tag="ERROR:")
        self.worker = None
        self._set_inputs_enabled(True)

    def _stop(self):
        if self.worker:
            self.worker.cancel()

    def _open_settings(self):
        dlg = SettingsDialog(self, self.settings, self.api_key)
        if dlg.exec() == QDialog.Accepted:
            new_settings, new_key = dlg.values()
            settings_mod.save_settings(new_settings)
            if new_key and new_key != self.api_key:
                settings_mod.set_api_key(new_key)
            self.settings = new_settings
            self.api_key = settings_mod.get_api_key()
            self._on_settings_changed()
            self._append_chat("system", "Settings saved.", colour="#1b5e20", tag="SYSTEM:")

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
        self._append_chat("system", f"Reindex started from {self.settings.library_path}", colour="#1b5e20", tag="SYSTEM:")

    @Slot(int, int)
    def _on_ingest_progress(self, done: int, total: int):
        if total:
            self.progress.setValue(int(done * 100 / total))

    @Slot(object)
    def _on_ingest_done(self, report):
        self.progress.setVisible(False)
        self._append_chat("system",
            f"Reindex complete: {report.versions_seen} versions, {report.chunks_created} chunks, {report.duration_s:.1f}s",
            colour="#1b5e20", tag="SYSTEM:")
        self.ingest_worker = None
        self._set_inputs_enabled(True)

    @Slot(str)
    def _on_ingest_failed(self, err: str):
        self.progress.setVisible(False)
        self._append_chat("system", f"Reindex failed: {err}", colour="#c62828", tag="ERROR:")
        self.ingest_worker = None
        self._set_inputs_enabled(True)

    def _set_inputs_enabled(self, enabled: bool):
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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Contoso KB Chatbot")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

---

## APPENDIX I — PyInstaller

### `ContosoKBChatbot.spec`

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("PySide6", "sentence_transformers", "chromadb", "anthropic", "keyring", "markdown"):
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
        "torch.cuda", "torch.distributed", "torchvision", "torchaudio",
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

### `build_chatbot_exe.bat`

```batch
@echo off
setlocal
pushd "%~dp0"
echo Building ContosoKBChatbot.exe...
"scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBChatbot.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo.
echo Build complete. Artifact: dist\ContosoKBChatbot.exe
pause
popd
endlocal
```
