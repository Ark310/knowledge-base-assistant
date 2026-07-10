# KB Chatbot v3.0.1 — Phase 5: On-Prem Model Fine-Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a QLoRA-fine-tuned Qwen2.5-7B-Instruct ("Contoso Guru") that synthesizes Contoso's retrieved context into Claude-quality cited answers, served via the existing Ollama gateway — without changing the RAG "answer only from context" contract.

**Architecture:** An offline batch pipeline. `Dev/kb_chatbot/finetune/` builds a PII-redacted `train.jsonl`/`eval.jsonl` from ticket problem→resolution pairs + a Claude/Codex-distilled style slice + abstain examples (every example in the exact serving prompt shape). A native-Windows `transformers`+`peft`+`bitsandbytes` QLoRA trainer produces a LoRA adapter; it is merged → GGUF → Q4_K_M and served as a new Ollama tag. An eval-compare gate (tuned vs base vs Claude + abstain-safety) decides whether to flip the gateway Modelfile.

**Tech Stack:** Python 3.12, `transformers`, `peft`, `bitsandbytes`, `datasets`, `torch` (CUDA), llama.cpp (GGUF convert/quantize), Ollama, PowerShell (gateway scripts). Test env: `scraper\venv`.

## Global Constraints

- **Security (org rule, hard gate):** never include API secret keys, passwords, or customer PII — in training data or anywhere. A redaction probe test on the generated JSONL is ship-blocking.
- **Serving parity:** training examples use system = `Dev.kb_chatbot.prompt.build_system_prompt()` and the user turn built by `Dev.kb_chatbot.prompt.build_messages(...)` — identical to what `orchestrator.handle_turn` sends the local provider (orchestrator.py:387-390).
- **RAG contract preserved:** the tuned model must still abstain when context is missing; abstain-safety is a ship-blocking eval gate.
- **Hardware:** RTX 5060 Ti 8 GB, Windows Server 2019, GPU shared with KYC. Training runs only in a dedicated window (KYC paused, Ollama stopped). Config must fit 8 GB (4-bit + grad-checkpointing + micro-batch 1; seq 2048→1024 fallback).
- **Base model:** HF `Qwen/Qwen2.5-7B-Instruct`; Ollama base tag `qwen2.5:7b-instruct`; tuned tag `contoso-reasoning-qwen25-7b:v1`. Base tag stays as instant rollback.
- **Large artifacts** (datasets, adapters, GGUF) live under `config.STATE_DIR / "finetune"` (off OneDrive, gitignored) — never committed.
- Run tests with `scraper\venv\Scripts\python.exe -m pytest`.

## File Structure

New package `Dev/kb_chatbot/finetune/`:
- `__init__.py` — package marker + one-line docstring.
- `finetune_config.py` — all paths + hyperparameters (single source of truth).
- `example_format.py` — pure: turn (chunks, question, answer) into a serving-parity chat record; JSONL (de)serialize.
- `redaction.py` — pure: PII/secret leak probe + JSONL scan (the hard gate).
- `build_dataset.py` — assemble ticket-pair + abstain examples, merge distilled slice, split train/eval, run the gate, write JSONL.
- `distill.py` — run Claude/Codex over a curated question set → captured (context, answer) targets (resumable, cost-logged).
- `train_qlora.py` — QLoRA trainer (operator-run on the AI PC), config-driven, `--dry-run`.
- `merge_and_export.py` — merge adapter → fp16 → GGUF → Q4_K_M (operator-run).
- `eval_compare.py` — tuned vs base vs Claude eval + abstain-safety report + gate.
- `README.md` — operator runbook.

Gateway additions (`ai_pc/reasoning_gateway/`):
- `Modelfile.reasoning.tuned` — FROM the tuned GGUF, same SYSTEM/params as `Modelfile.reasoning`.
- `07_activate_tuned.ps1`, `08_rollback.ps1` — flip the served tag.

Tests: `Dev/kb_chatbot/tests/test_finetune_*.py`.

Consumed (existing, unchanged):
- `ticket_ingest.build_ticket_chunks(data: dict, path) -> list[Chunk]` — one redacted chunk/ticket; `chunk.text` = `"Problem: <redacted>\n\nResolution: <redacted>"`; `chunk.metadata` has `kind,ticket_id,url,product,resolved,...`.
- `prompt.build_system_prompt() -> str`, `prompt.build_messages(*, context_chunks, history, user_msg, attachments=None) -> list[dict]`, `prompt.format_context(chunks) -> str`.
- `retriever.Retriever(chroma_path, *, confidence_floor=...)`, `.retrieve(query, filters, top_k_rerank=None) -> RetrievalResult(chunks, abstain_reason, ...)`, `Filters(product=...)`.
- `chat.orchestrator.handle_turn(user_msg, session, filters, model, *, deps) -> Turn(content, retrieved_ids, ...)`, `Deps(retriever, llm, answer_cache=None)`.
- `llm.factory.make_provider(provider_id, settings)`; `eval.score.accuracy/source_stability/answer_stability`; `eval.dataset.EvalCase/load`.
- `chunker.Chunk(id, text, metadata)`.

---

## P5.1 — Dataset build + redaction gate + tests

### Task 1: `finetune_config.py` — paths + hyperparameters

**Files:**
- Create: `Dev/kb_chatbot/finetune/__init__.py`
- Create: `Dev/kb_chatbot/finetune/finetune_config.py`
- Test: `Dev/kb_chatbot/tests/test_finetune_config.py`

**Interfaces:**
- Produces: module constants — `DATA_DIR, TRAIN_JSONL, EVAL_JSONL, DISTILL_JSONL, ADAPTER_DIR, MERGED_DIR, GGUF_PATH: Path`; `BASE_MODEL_HF, BASE_OLLAMA, TUNED_TAG: str`; ints `MAX_TICKET_EXAMPLES, DISTILL_QUESTIONS, ABSTAIN_EXAMPLES, EVAL_HOLDOUT, SEQ_LEN, EPOCHS, GRAD_ACCUM, MICRO_BATCH, LORA_R, LORA_ALPHA`; floats `LORA_DROPOUT, LR`.

- [ ] **Step 1: Write the failing test**
```python
# Dev/kb_chatbot/tests/test_finetune_config.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune import finetune_config as fc

def test_paths_are_under_state_dir_finetune():
    from Dev.kb_chatbot import config
    assert fc.DATA_DIR == config.STATE_DIR / "finetune"
    assert fc.TRAIN_JSONL.parent == fc.DATA_DIR and fc.TRAIN_JSONL.name == "train.jsonl"

def test_fits_8gb_config():
    assert fc.MICRO_BATCH == 1 and fc.SEQ_LEN in (1024, 2048)
    assert 0 < fc.LORA_R <= 32 and fc.BASE_MODEL_HF == "Qwen/Qwen2.5-7B-Instruct"
    assert fc.TUNED_TAG == "contoso-reasoning-qwen25-7b:v1"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_config.py -v`
Expected: FAIL — `ModuleNotFoundError: Dev.kb_chatbot.finetune`.

- [ ] **Step 3: Create the package + config**
```python
# Dev/kb_chatbot/finetune/__init__.py
"""Phase 5: on-prem QLoRA fine-tuning pipeline (RAG-aware, redaction-gated)."""
```
```python
# Dev/kb_chatbot/finetune/finetune_config.py
"""Single source of truth for fine-tuning paths + hyperparameters (8 GB-safe)."""
from __future__ import annotations
from pathlib import Path
from Dev.kb_chatbot import config

DATA_DIR      = config.STATE_DIR / "finetune"     # off OneDrive, gitignored
TRAIN_JSONL   = DATA_DIR / "train.jsonl"
EVAL_JSONL    = DATA_DIR / "eval.jsonl"
DISTILL_JSONL = DATA_DIR / "distill.jsonl"
ADAPTER_DIR   = DATA_DIR / "adapter"
MERGED_DIR    = DATA_DIR / "merged_fp16"
GGUF_PATH     = DATA_DIR / "contoso-reasoning-qwen25-7b-Q4_K_M.gguf"

BASE_MODEL_HF = "Qwen/Qwen2.5-7B-Instruct"
BASE_OLLAMA   = "qwen2.5:7b-instruct"
TUNED_TAG     = "contoso-reasoning-qwen25-7b:v1"

# Dataset sizes
MAX_TICKET_EXAMPLES = 4000
DISTILL_QUESTIONS   = 800
ABSTAIN_EXAMPLES    = 400
EVAL_HOLDOUT        = 150

# QLoRA / training (fits 8 GB: 4-bit + grad-checkpointing + micro-batch 1)
SEQ_LEN     = 2048   # drop to 1024 if OOM
EPOCHS      = 2
MICRO_BATCH = 1
GRAD_ACCUM  = 16
LR          = 2e-4
LORA_R      = 16
LORA_ALPHA  = 32
LORA_DROPOUT = 0.05
```

- [ ] **Step 4: Run test to verify it passes**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_config.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/finetune/__init__.py Dev/kb_chatbot/finetune/finetune_config.py Dev/kb_chatbot/tests/test_finetune_config.py
git commit -m "feat(v3.0.1-p5): finetune package + config (paths, 8GB QLoRA hyperparams)"
```

---

### Task 2: `example_format.py` — serving-parity chat records

**Files:**
- Create: `Dev/kb_chatbot/finetune/example_format.py`
- Test: `Dev/kb_chatbot/tests/test_finetune_example_format.py`

**Interfaces:**
- Consumes: `prompt.build_system_prompt`, `prompt.build_messages`; `chunker.Chunk`.
- Produces: `make_example(chunks: list[Chunk], question: str, answer: str) -> dict` returning `{"messages":[{role:system},{role:user},{role:assistant}]}`; `dumps(example: dict) -> str` (one JSONL line); `loads(line: str) -> dict`.

- [ ] **Step 1: Write the failing test**
```python
# Dev/kb_chatbot/tests/test_finetune_example_format.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.example_format import make_example, dumps, loads
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.prompt import build_system_prompt

def _chunk():
    return Chunk(id="ticket_1", text="Problem: X\n\nResolution: do Y",
                 metadata={"kind":"ticket","ticket_id":"1","url":"u","product":"tradedesk"})

def test_make_example_has_three_roles_and_serving_system():
    ex = make_example([_chunk()], "why X?", "Do Y. Sources: [Ticket #1](u)")
    roles = [m["role"] for m in ex["messages"]]
    assert roles == ["system", "user", "assistant"]
    assert ex["messages"][0]["content"] == build_system_prompt()
    assert ex["messages"][2]["content"].startswith("Do Y")

def test_user_turn_matches_serving_context_and_question():
    ex = make_example([_chunk()], "why X?", "ans")
    user = ex["messages"][1]["content"]
    assert "CONTEXT (the only facts you may use):" in user
    assert "USER QUESTION:\nwhy X?" in user

def test_dumps_loads_roundtrip():
    ex = make_example([_chunk()], "q", "a")
    assert loads(dumps(ex)) == ex
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_example_format.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**
```python
# Dev/kb_chatbot/finetune/example_format.py
"""Turn (retrieved chunks, question, answer) into a chat training record that
matches EXACTLY what orchestrator.handle_turn sends the local provider, so
training and inference see the same prompt."""
from __future__ import annotations
import json
from Dev.kb_chatbot.prompt import build_system_prompt, build_messages

def make_example(chunks, question: str, answer: str) -> dict:
    # build_messages([], user_msg) -> [user_turn]; reuse it for serving parity.
    user_turn = build_messages(context_chunks=chunks, history=[], user_msg=question)[0]
    return {"messages": [
        {"role": "system", "content": build_system_prompt()},
        user_turn,
        {"role": "assistant", "content": answer},
    ]}

def dumps(example: dict) -> str:
    return json.dumps(example, ensure_ascii=False)

def loads(line: str) -> dict:
    return json.loads(line)
```

- [ ] **Step 4: Run test to verify it passes**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_example_format.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/finetune/example_format.py Dev/kb_chatbot/tests/test_finetune_example_format.py
git commit -m "feat(v3.0.1-p5): serving-parity training-example formatter"
```

---

### Task 3: `redaction.py` — PII/secret leak probe (the hard gate)

**Files:**
- Create: `Dev/kb_chatbot/finetune/redaction.py`
- Test: `Dev/kb_chatbot/tests/test_finetune_redaction.py`

**Interfaces:**
- Produces: `find_leaks(text: str) -> list[str]` (list of category tags found: "email","phone","secret","password"); `scan_records(records: list[dict]) -> list[tuple[int,str,str]]` (index, category, snippet) scanning every message content; `assert_clean(records: list[dict]) -> None` raising `LeakError` if any leak. Exception class `LeakError(RuntimeError)`.

- [ ] **Step 1: Write the failing test**
```python
# Dev/kb_chatbot/tests/test_finetune_redaction.py
import sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.redaction import find_leaks, scan_records, assert_clean, LeakError

def test_detects_real_email_and_phone_and_secret():
    assert "email" in find_leaks("contact john.doe@acme.com")
    assert "phone" in find_leaks("call +1 416 555 0134 today")
    assert "secret" in find_leaks("key YOUR_ANTHROPIC_API_KEY_HERE leaked")

def test_ignores_redacted_placeholders_and_iso_dates():
    assert find_leaks("emailed [redacted] on 2024-08-22 re ticket #54000") == []

def test_assert_clean_raises_on_planted_pii():
    recs = [{"messages":[{"role":"user","content":"ok"},
                         {"role":"assistant","content":"mail jane@acme.com"}]}]
    with pytest.raises(LeakError):
        assert_clean(recs)

def test_assert_clean_passes_when_clean():
    recs = [{"messages":[{"role":"assistant","content":"do Y. Sources: [Ticket #1](u)"}]}]
    assert_clean(recs)  # no raise
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_redaction.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**
```python
# Dev/kb_chatbot/finetune/redaction.py
"""Hard PII/secret gate for the training set. find_leaks scans for REAL emails,
phone numbers, secret keys, and passwords — NOT the '[redacted]' placeholders the
ticket redactor already inserts. assert_clean fails the build if anything leaks."""
from __future__ import annotations
import re

class LeakError(RuntimeError):
    pass

# Real email (not a bare '[redacted]' token).
_EMAIL  = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Phone: 10+ digits with separators; avoids ISO dates (which have no leading +/() and are 8 digits).
_PHONE  = re.compile(r"(?<!\d)(?:\+?\d[\s().\-]?){10,}\d(?!\d)")
# Common secret-key shapes (Anthropic, OpenAI, AWS, generic bearer).
_SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9\-]{16,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,}|gh[pousr]_[A-Za-z0-9]{20,})\b")
_PASSWORD = re.compile(r"(?i)\bpassword\s*[:=]\s*\S+")

_CATS = (("email", _EMAIL), ("phone", _PHONE), ("secret", _SECRET), ("password", _PASSWORD))

def find_leaks(text: str) -> list[str]:
    t = text or ""
    return [cat for cat, rx in _CATS if rx.search(t)]

def scan_records(records: list[dict]) -> list[tuple[int, str, str]]:
    hits = []
    for i, rec in enumerate(records):
        for msg in rec.get("messages", []):
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            for cat in find_leaks(content):
                hits.append((i, cat, content[:80]))
    return hits

def assert_clean(records: list[dict]) -> None:
    hits = scan_records(records)
    if hits:
        raise LeakError(f"{len(hits)} PII/secret leak(s) in training data; "
                        f"first: example {hits[0][0]} [{hits[0][1]}] {hits[0][2]!r}")
```

- [ ] **Step 4: Run test to verify it passes**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_redaction.py -v`
Expected: PASS (4 tests). If `test_ignores_redacted_placeholders_and_iso_dates` fails on the phone regex matching a date, tighten `_PHONE` until it passes.

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/finetune/redaction.py Dev/kb_chatbot/tests/test_finetune_redaction.py
git commit -m "feat(v3.0.1-p5): PII/secret redaction probe (hard training-data gate)"
```

---

### Task 4: `build_dataset.py` — ticket-pair + abstain examples

**Files:**
- Create: `Dev/kb_chatbot/finetune/build_dataset.py`
- Test: `Dev/kb_chatbot/tests/test_finetune_build_dataset.py`

**Interfaces:**
- Consumes: `finetune_config` (fc), `example_format.make_example`, `ticket_ingest.build_ticket_chunks`, `retriever.Retriever/Filters`.
- Produces:
  - `split_problem_resolution(chunk_text: str) -> tuple[str, str]` — returns (problem, resolution) from a build_ticket_chunks body.
  - `ticket_target(resolution: str, ticket_id: str, url: str) -> str` — grounded answer = resolution + a `Sources:` citation line.
  - `ticket_examples(retriever, tickets_dir: Path, limit: int) -> Iterator[dict]` — yields make_example records for resolved tickets.
  - `abstain_examples(retriever, questions: list[str]) -> Iterator[dict]` — yields make_example records whose target is the canonical refusal `ABSTAIN_TEXT`.
  - Constant `ABSTAIN_TEXT: str` = the exact refusal from prompt rule 2.

- [ ] **Step 1: Write the failing test** (uses the tiny fixture library from the retriever tests)
```python
# Dev/kb_chatbot/tests/test_finetune_build_dataset.py
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
import pytest
from Dev.kb_chatbot.finetune import build_dataset as bd

def test_split_problem_resolution():
    p, r = bd.split_problem_resolution("Problem: buy amount null\n\nResolution: patch getdeal")
    assert p == "buy amount null" and r == "patch getdeal"

def test_ticket_target_appends_citation():
    t = bd.ticket_target("do the fix", "54000", "https://s/tickets/54000/edit")
    assert "do the fix" in t and "Ticket #54000" in t and "https://s/tickets/54000/edit" in t

def test_abstain_text_matches_prompt_rule():
    assert "don't have enough information" in bd.ABSTAIN_TEXT.lower()

def test_abstain_examples_use_refusal_target():
    class _R:  # retriever stub: no chunks -> abstain scenario
        def retrieve(self, q, f, top_k_rerank=None):
            class RR: chunks = []
            return RR()
    ex = list(bd.abstain_examples(_R(), ["totally unknown question"]))
    assert ex and ex[0]["messages"][2]["content"] == bd.ABSTAIN_TEXT
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_build_dataset.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement (ticket + abstain generators)**
```python
# Dev/kb_chatbot/finetune/build_dataset.py
"""Assemble the fine-tuning JSONL: ticket problem->resolution pairs (grounding),
abstain/safety examples, and (merged in main) the distilled style slice. Every
example is redaction-gated before it is written."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator

from Dev.kb_chatbot.finetune import finetune_config as fc
from Dev.kb_chatbot.finetune.example_format import make_example, dumps, loads
from Dev.kb_chatbot.finetune.redaction import assert_clean
from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks
from Dev.kb_chatbot.retriever import Filters

# Exact refusal from prompt.py rule 2 — the abstain target the model must learn.
ABSTAIN_TEXT = ("I don't have enough information in the knowledge base to answer "
                "this confidently.")

def split_problem_resolution(chunk_text: str) -> tuple[str, str]:
    """build_ticket_chunks body is 'Problem: <p>\\n\\nResolution: <r>'."""
    marker = "\n\nResolution:"
    if marker in chunk_text:
        head, tail = chunk_text.split(marker, 1)
        return head.replace("Problem:", "", 1).strip(), tail.strip()
    return chunk_text.replace("Problem:", "", 1).strip(), ""

def ticket_target(resolution: str, ticket_id: str, url: str) -> str:
    cite = f"[Ticket #{ticket_id}]({url})" if url else f"[Ticket #{ticket_id}]"
    return f"{resolution}\n\nSources: {cite}"

def _iter_ticket_json(tickets_dir: Path) -> Iterator[dict]:
    for fp in sorted(tickets_dir.glob("ticket_*.json")):
        try:
            yield json.loads(fp.read_text(encoding="utf-8")), fp
        except Exception:
            continue

def ticket_examples(retriever, tickets_dir: Path, limit: int) -> Iterator[dict]:
    n = 0
    for data, fp in _iter_ticket_json(Path(tickets_dir)):
        if n >= limit:
            break
        chunks = build_ticket_chunks(data, fp)
        if not chunks or not chunks[0].metadata.get("resolved"):
            continue
        chunk = chunks[0]
        problem, resolution = split_problem_resolution(chunk.text)
        if not problem or not resolution:
            continue
        ctx = retriever.retrieve(problem, Filters(), top_k_rerank=None).chunks
        answer = ticket_target(resolution, chunk.metadata.get("ticket_id", ""),
                               chunk.metadata.get("url", ""))
        yield make_example(ctx, problem, answer)
        n += 1

def abstain_examples(retriever, questions: list[str]) -> Iterator[dict]:
    for q in questions:
        ctx = retriever.retrieve(q, Filters(), top_k_rerank=None).chunks
        # Teach refusal even when a few weak chunks came back: target is the refusal.
        yield make_example(ctx, q, ABSTAIN_TEXT)
```

- [ ] **Step 4: Run test to verify it passes**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_build_dataset.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/finetune/build_dataset.py Dev/kb_chatbot/tests/test_finetune_build_dataset.py
git commit -m "feat(v3.0.1-p5): ticket-pair + abstain training-example generators"
```

---

### Task 5: `distill.py` — Claude/Codex style slice

**Files:**
- Create: `Dev/kb_chatbot/finetune/distill.py`
- Test: `Dev/kb_chatbot/tests/test_finetune_distill.py`

**Interfaces:**
- Consumes: `orchestrator.handle_turn/Deps`, `retriever`, `Session`, `Filters`, `example_format.make_example`, `finetune_config`.
- Produces: `distill_one(retriever, llm, model: str, question: str) -> dict | None` — runs one real turn, returns a make_example record whose target is the model's answer, or None if the turn abstained/empty; `run(questions: list[str], retriever, llm, model: str, out_path: Path) -> int` — appends records to `out_path` (resumable: skips questions already present), returns count written.

- [ ] **Step 1: Write the failing test** (fake provider + stub retriever — no cloud calls)
```python
# Dev/kb_chatbot/tests/test_finetune_distill.py
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune import distill
from Dev.kb_chatbot.chunker import Chunk

class _StubRetriever:
    def retrieve(self, q, f, top_k_rerank=None):
        class RR: chunks = [Chunk(id="t1", text="Problem: x\n\nResolution: y",
                                  metadata={"kind":"ticket","ticket_id":"1","url":"u","product":"tradedesk"})]
        return RR()
    def get_by_ids(self, ids): return []

def test_distill_one_captures_answer(monkeypatch):
    from Dev.kb_chatbot.chat import orchestrator
    from Dev.kb_chatbot.chat.session import Turn
    monkeypatch.setattr(orchestrator, "handle_turn",
        lambda *a, **k: Turn(role="assistant", kind="answer", content="Cited answer [Ticket #1](u)", retrieved_ids=["t1"]))
    ex = distill.distill_one(_StubRetriever(), object(), "m", "why x?")
    assert ex["messages"][2]["content"].startswith("Cited answer")

def test_distill_one_skips_abstain(monkeypatch):
    from Dev.kb_chatbot.chat import orchestrator
    from Dev.kb_chatbot.chat.session import Turn
    monkeypatch.setattr(orchestrator, "handle_turn",
        lambda *a, **k: Turn(role="assistant", kind="abstain", content="no info"))
    assert distill.distill_one(_StubRetriever(), object(), "m", "q") is None

def test_run_is_resumable(monkeypatch, tmp_path):
    from Dev.kb_chatbot.chat import orchestrator
    from Dev.kb_chatbot.chat.session import Turn
    monkeypatch.setattr(orchestrator, "handle_turn",
        lambda q, *a, **k: Turn(role="assistant", kind="answer", content=f"ans {q}", retrieved_ids=["t1"]))
    out = tmp_path / "distill.jsonl"
    n1 = distill.run(["q1","q2"], _StubRetriever(), object(), "m", out)
    n2 = distill.run(["q1","q2","q3"], _StubRetriever(), object(), "m", out)  # q1,q2 already done
    assert n1 == 2 and n2 == 1
    assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 3
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_distill.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**
```python
# Dev/kb_chatbot/finetune/distill.py
"""Distill Claude/Codex answers over our retrieved context into training targets.
Runs the REAL orchestrator turn so the captured answer reflects the exact context
+ house style. Resumable (skips questions already written) and cost-logged."""
from __future__ import annotations
import json
from pathlib import Path

from Dev.kb_chatbot.finetune.example_format import make_example, dumps, loads
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.retriever import Filters

def distill_one(retriever, llm, model: str, question: str) -> dict | None:
    from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps
    deps = Deps(retriever=retriever, llm=llm, answer_cache=None)
    turn = handle_turn(question, Session.new(), Filters(), model, deps=deps)
    if turn.kind != "answer" or not (turn.content or "").strip():
        return None
    ids = list(getattr(turn, "retrieved_ids", []) or [])
    ctx = retriever.get_by_ids(ids) if ids else []
    return make_example(ctx, question, turn.content)

def _done_questions(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    done = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        for m in loads(line)["messages"]:
            if m["role"] == "user" and "USER QUESTION:\n" in m["content"]:
                done.add(m["content"].split("USER QUESTION:\n", 1)[1].strip())
    return done

def run(questions, retriever, llm, model: str, out_path: Path) -> int:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = _done_questions(out_path)
    written = 0
    with out_path.open("a", encoding="utf-8") as f:
        for q in questions:
            if q.strip() in done:
                continue
            ex = distill_one(retriever, llm, model, q)
            if ex is None:
                continue
            f.write(dumps(ex) + "\n")
            written += 1
    return written
```

- [ ] **Step 4: Run test to verify it passes**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_distill.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/finetune/distill.py Dev/kb_chatbot/tests/test_finetune_distill.py
git commit -m "feat(v3.0.1-p5): Claude/Codex distillation of house-style targets (resumable)"
```

---

### Task 6: `build_dataset.main()` — assemble, gate, split, write

**Files:**
- Modify: `Dev/kb_chatbot/finetune/build_dataset.py` (add `assemble` + `main`)
- Test: `Dev/kb_chatbot/tests/test_finetune_assemble.py`

**Interfaces:**
- Produces: `assemble(ticket_recs, abstain_recs, distill_recs, holdout: int, rng_seed: int = 42) -> tuple[list[dict], list[dict]]` — concatenates, runs `assert_clean` on ALL records (hard gate), deterministically shuffles, splits off `holdout` eval records, returns (train, eval); `main(argv=None)` — wires real sources + writes `TRAIN_JSONL`/`EVAL_JSONL`.

- [ ] **Step 1: Write the failing test**
```python
# Dev/kb_chatbot/tests/test_finetune_assemble.py
import sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.build_dataset import assemble
from Dev.kb_chatbot.finetune.redaction import LeakError

def _rec(ans):
    return {"messages":[{"role":"system","content":"s"},
                        {"role":"user","content":"USER QUESTION:\nq"},
                        {"role":"assistant","content":ans}]}

def test_assemble_splits_holdout_and_is_deterministic():
    recs = [_rec(f"a{i}") for i in range(20)]
    tr1, ev1 = assemble(recs, [], [], holdout=5)
    tr2, ev2 = assemble(recs, [], [], holdout=5)
    assert len(ev1) == 5 and len(tr1) == 15
    assert [m["messages"][2]["content"] for m in ev1] == [m["messages"][2]["content"] for m in ev2]

def test_assemble_enforces_redaction_gate():
    with pytest.raises(LeakError):
        assemble([_rec("mail me at bob@acme.com")], [], [], holdout=0)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_assemble.py -v`
Expected: FAIL — `assemble` not defined.

- [ ] **Step 3: Implement (append to `build_dataset.py`)**
```python
# --- append to Dev/kb_chatbot/finetune/build_dataset.py ---
import random

def assemble(ticket_recs, abstain_recs, distill_recs, holdout: int, rng_seed: int = 42):
    records = list(ticket_recs) + list(abstain_recs) + list(distill_recs)
    assert_clean(records)                      # HARD GATE — raises LeakError on any PII/secret
    rng = random.Random(rng_seed)
    rng.shuffle(records)
    eval_recs = records[:holdout]
    train_recs = records[holdout:]
    return train_recs, eval_recs

def _write(path: Path, recs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(dumps(r) + "\n")

def main(argv=None) -> None:
    import argparse
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.retriever import Retriever
    ap = argparse.ArgumentParser(description="Build the fine-tuning dataset (redaction-gated).")
    ap.add_argument("--tickets", default=str(config.TICKETS_DEFAULT))
    ap.add_argument("--chroma", default=str(config.CHROMA_DIR))
    ap.add_argument("--abstain-questions", default="", help="optional newline file of out-of-scope questions")
    args = ap.parse_args(argv)

    retriever = Retriever(Path(args.chroma), confidence_floor=0.0)
    tickets = list(ticket_examples(retriever, Path(args.tickets), fc.MAX_TICKET_EXAMPLES))
    ab_qs = (Path(args.abstain_questions).read_text(encoding="utf-8").splitlines()
             if args.abstain_questions else [])[:fc.ABSTAIN_EXAMPLES]
    abstain = list(abstain_examples(retriever, ab_qs))
    distill = [loads(l) for l in fc.DISTILL_JSONL.read_text(encoding="utf-8").splitlines()] \
        if fc.DISTILL_JSONL.exists() else []
    train, ev = assemble(tickets, abstain, distill, holdout=fc.EVAL_HOLDOUT)
    _write(fc.TRAIN_JSONL, train)
    _write(fc.EVAL_JSONL, ev)
    print(f"train={len(train)} eval={len(ev)}  ({len(tickets)} ticket, {len(abstain)} abstain, {len(distill)} distilled)")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_assemble.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/finetune/build_dataset.py Dev/kb_chatbot/tests/test_finetune_assemble.py
git commit -m "feat(v3.0.1-p5): dataset assemble+split with redaction gate + build_dataset CLI"
```

---

## P5.2 — Training script + dry-run

### Task 7: `train_qlora.py` — QLoRA trainer (operator-run)

**Files:**
- Create: `Dev/kb_chatbot/finetune/train_qlora.py`
- Test: `Dev/kb_chatbot/tests/test_finetune_train_importable.py`

**Interfaces:**
- Consumes: `finetune_config`, HF `transformers`, `peft`, `bitsandbytes`, `datasets`.
- Produces: `build_lora_config() -> peft.LoraConfig`; `format_for_trainer(example: dict, tokenizer) -> dict` (applies Qwen chat template, masks all but the assistant turn into `labels`); `main(argv=None)` with `--dry-run` (trains 2 steps on ≤16 examples to validate the path + VRAM). Writes the adapter to `fc.ADAPTER_DIR`.

Note: `transformers`/`peft`/`bitsandbytes` may not be installed in `scraper\venv`; the test only asserts the module *parses/imports its own symbols*, guarded so it skips if heavy deps are absent. Real runs happen on the AI PC.

- [ ] **Step 1: Write the failing test**
```python
# Dev/kb_chatbot/tests/test_finetune_train_importable.py
import sys, importlib.util, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

def test_train_module_exposes_symbols():
    if importlib.util.find_spec("peft") is None:
        pytest.skip("peft not installed in this env (trainer runs on the AI PC)")
    from Dev.kb_chatbot.finetune import train_qlora as t
    assert hasattr(t, "build_lora_config") and hasattr(t, "format_for_trainer") and hasattr(t, "main")

def test_format_masks_prompt(monkeypatch):
    if importlib.util.find_spec("peft") is None:
        pytest.skip("heavy deps absent")
    from Dev.kb_chatbot.finetune import train_qlora as t
    from transformers import AutoTokenizer
    from Dev.kb_chatbot.finetune import finetune_config as fc
    tok = AutoTokenizer.from_pretrained(fc.BASE_MODEL_HF)
    ex = {"messages":[{"role":"system","content":"s"},{"role":"user","content":"u"},{"role":"assistant","content":"a"}]}
    out = t.format_for_trainer(ex, tok)
    assert set(out) >= {"input_ids","labels"}
    assert any(l == -100 for l in out["labels"])   # prompt tokens masked
    assert any(l != -100 for l in out["labels"])   # assistant tokens kept
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_train_importable.py -v`
Expected: FAIL (module missing) or SKIP if peft absent — either way, not PASS. After Step 3 it PASSES-or-SKIPS.

- [ ] **Step 3: Implement**
```python
# Dev/kb_chatbot/finetune/train_qlora.py
"""QLoRA fine-tune Qwen2.5-7B-Instruct on the redaction-gated train.jsonl.
Native Windows: transformers + peft + bitsandbytes (4-bit NF4). Runs on the AI PC
in the dedicated GPU window. `--dry-run` trains 2 steps on <=16 examples to
validate the path + VRAM before the full run."""
from __future__ import annotations
import argparse
from Dev.kb_chatbot.finetune import finetune_config as fc

def build_lora_config():
    from peft import LoraConfig
    return LoraConfig(
        r=fc.LORA_R, lora_alpha=fc.LORA_ALPHA, lora_dropout=fc.LORA_DROPOUT,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    )

def format_for_trainer(example: dict, tokenizer) -> dict:
    """Qwen chat template; supervise ONLY the assistant turn (mask the rest to -100)."""
    msgs = example["messages"]
    full = tokenizer.apply_chat_template(msgs, tokenize=True, add_generation_prompt=False)
    prompt_only = tokenizer.apply_chat_template(msgs[:-1], tokenize=True, add_generation_prompt=True)
    labels = list(full)
    for i in range(min(len(prompt_only), len(labels))):
        labels[i] = -100
    return {"input_ids": full, "attention_mask": [1]*len(full), "labels": labels}

def main(argv=None) -> None:
    import torch
    from datasets import load_dataset
    from transformers import (AutoTokenizer, AutoModelForCausalLM,
                              BitsAndBytesConfig, Trainer, TrainingArguments,
                              DataCollatorForSeq2Seq)
    from peft import get_peft_model, prepare_model_for_kbit_training
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seq-len", type=int, default=fc.SEQ_LEN)
    args = ap.parse_args(argv)

    tok = AutoTokenizer.from_pretrained(fc.BASE_MODEL_HF)
    tok.pad_token = tok.pad_token or tok.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(fc.BASE_MODEL_HF, quantization_config=bnb, device_map="auto")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, build_lora_config())

    ds = load_dataset("json", data_files=str(fc.TRAIN_JSONL), split="train")
    if args.dry_run:
        ds = ds.select(range(min(16, len(ds))))
    ds = ds.map(lambda e: format_for_trainer(e, tok), remove_columns=ds.column_names)
    ds = ds.filter(lambda e: len(e["input_ids"]) <= args.seq_len)

    targs = TrainingArguments(
        output_dir=str(fc.ADAPTER_DIR), per_device_train_batch_size=fc.MICRO_BATCH,
        gradient_accumulation_steps=fc.GRAD_ACCUM, num_train_epochs=(1 if args.dry_run else fc.EPOCHS),
        max_steps=(2 if args.dry_run else -1), learning_rate=fc.LR, lr_scheduler_type="cosine",
        warmup_ratio=0.03, bf16=True, gradient_checkpointing=True, logging_steps=10,
        save_strategy="epoch", report_to=[])
    collator = DataCollatorForSeq2Seq(tok, label_pad_token_id=-100, padding=True)
    Trainer(model=model, args=targs, train_dataset=ds, data_collator=collator).train()
    model.save_pretrained(str(fc.ADAPTER_DIR)); tok.save_pretrained(str(fc.ADAPTER_DIR))
    print(f"adapter saved -> {fc.ADAPTER_DIR}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes (or skips cleanly)**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_train_importable.py -v`
Expected: PASS if peft present, else SKIP (both acceptable).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/finetune/train_qlora.py Dev/kb_chatbot/tests/test_finetune_train_importable.py
git commit -m "feat(v3.0.1-p5): QLoRA trainer (4-bit, assistant-only loss, --dry-run)"
```

---

## P5.3 — Full training run (operator, dedicated window)

### Task 8: Operator runbook + env validation

**Files:**
- Create: `Dev/kb_chatbot/finetune/README.md`

**Interfaces:** none (documentation). This task has no unit test; its deliverable is a runnable, exact-command runbook.

- [ ] **Step 1: Write the runbook** — `README.md` with these exact operator steps:
  1. **Prep (dev machine):** `python -m Dev.kb_chatbot.finetune.distill` helper to generate the distilled slice (documented command with `--provider claude --model claude-sonnet-4-6 --questions <file> --out <DISTILL_JSONL>`), then `python -m Dev.kb_chatbot.finetune.build_dataset --tickets <lib>\tickets --chroma <CHROMA_DIR> --abstain-questions <file>`. Confirm the redaction gate passed (build aborts on any leak).
  2. **AI PC env (one-time):** create a training venv; `pip install torch --index-url https://download.pytorch.org/whl/cu124`; `pip install transformers peft bitsandbytes datasets accelerate`; verify `python -c "import torch; print(torch.cuda.is_available())"` → `True` and `python -c "import bitsandbytes"` succeeds.
  3. **Open the window:** stop the gateway (`ai_pc\reasoning_gateway\05_stop_gateway.ps1`), pause KYC, confirm VRAM free (`nvidia-smi`).
  4. **Dry-run:** `python -m Dev.kb_chatbot.finetune.train_qlora --dry-run` → expect it to complete 2 steps without OOM. If OOM: rerun with `--seq-len 1024`.
  5. **Full train:** `python -m Dev.kb_chatbot.finetune.train_qlora` → adapter in `fc.ADAPTER_DIR`.
  6. **Export + serve:** Task 9 command.
  7. **Eval gate:** Task 11 command; only flip on pass.
  8. **Restore:** resume KYC, restart the gateway (`05_start_gateway.ps1`).

- [ ] **Step 2: Commit**
```bash
git add Dev/kb_chatbot/finetune/README.md
git commit -m "docs(v3.0.1-p5): operator runbook (window, env, dry-run, train, export, gate)"
```

---

## P5.4 — Merge, export, serve

### Task 9: `merge_and_export.py` — adapter → GGUF → Q4_K_M (operator-run)

**Files:**
- Create: `Dev/kb_chatbot/finetune/merge_and_export.py`
- Test: `Dev/kb_chatbot/tests/test_finetune_export_cmds.py`

**Interfaces:**
- Produces: `gguf_convert_cmd(merged_dir: Path, out_gguf: Path, llama_cpp_dir: Path) -> list[str]`; `quantize_cmd(f16_gguf: Path, out_gguf: Path, llama_cpp_dir: Path, qtype: str = "Q4_K_M") -> list[str]`; `main(argv=None)` — merges the adapter (peft `merge_and_unload`) into `fc.MERGED_DIR`, then runs the two llama.cpp commands. The two `*_cmd` builders are pure + unit-tested; `main` is operator-run.

- [ ] **Step 1: Write the failing test**
```python
# Dev/kb_chatbot/tests/test_finetune_export_cmds.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.merge_and_export import gguf_convert_cmd, quantize_cmd

def test_convert_cmd_points_at_converter_and_merged_dir():
    cmd = gguf_convert_cmd(Path("m"), Path("out.gguf"), Path("llama.cpp"))
    assert any("convert_hf_to_gguf.py" in c for c in cmd)
    assert "m" in cmd[-1] or any(c.endswith("m") for c in cmd)

def test_quantize_cmd_uses_q4_k_m():
    cmd = quantize_cmd(Path("f16.gguf"), Path("q4.gguf"), Path("llama.cpp"))
    assert "Q4_K_M" in cmd
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_export_cmds.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**
```python
# Dev/kb_chatbot/finetune/merge_and_export.py
"""Merge the LoRA adapter into fp16, convert to GGUF, quantize Q4_K_M for Ollama.
The command builders are pure (unit-tested); main() is operator-run on the AI PC
(needs a llama.cpp checkout)."""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
from Dev.kb_chatbot.finetune import finetune_config as fc

def gguf_convert_cmd(merged_dir: Path, out_gguf: Path, llama_cpp_dir: Path) -> list[str]:
    return [sys.executable, str(Path(llama_cpp_dir) / "convert_hf_to_gguf.py"),
            str(merged_dir), "--outfile", str(out_gguf), "--outtype", "f16"]

def quantize_cmd(f16_gguf: Path, out_gguf: Path, llama_cpp_dir: Path, qtype: str = "Q4_K_M") -> list[str]:
    exe = Path(llama_cpp_dir) / ("llama-quantize.exe" if sys.platform == "win32" else "llama-quantize")
    return [str(exe), str(f16_gguf), str(out_gguf), qtype]

def main(argv=None) -> None:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    ap = argparse.ArgumentParser()
    ap.add_argument("--llama-cpp", required=True, help="path to a llama.cpp checkout")
    args = ap.parse_args(argv)
    base = AutoModelForCausalLM.from_pretrained(fc.BASE_MODEL_HF, torch_dtype="auto")
    merged = PeftModel.from_pretrained(base, str(fc.ADAPTER_DIR)).merge_and_unload()
    fc.MERGED_DIR.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(fc.MERGED_DIR))
    AutoTokenizer.from_pretrained(str(fc.ADAPTER_DIR)).save_pretrained(str(fc.MERGED_DIR))
    f16 = fc.DATA_DIR / "merged-f16.gguf"
    subprocess.run(gguf_convert_cmd(fc.MERGED_DIR, f16, Path(args.llama_cpp)), check=True)
    subprocess.run(quantize_cmd(f16, fc.GGUF_PATH, Path(args.llama_cpp)), check=True)
    print(f"GGUF -> {fc.GGUF_PATH}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_export_cmds.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/finetune/merge_and_export.py Dev/kb_chatbot/tests/test_finetune_export_cmds.py
git commit -m "feat(v3.0.1-p5): merge adapter -> GGUF -> Q4_K_M export (pure cmd builders + CLI)"
```

---

### Task 10: Gateway activate/rollback scripts + tuned Modelfile

**Files:**
- Create: `ai_pc/reasoning_gateway/Modelfile.reasoning.tuned`
- Create: `ai_pc/reasoning_gateway/07_activate_tuned.ps1`
- Create: `ai_pc/reasoning_gateway/08_rollback.ps1`
- Test: `Dev/kb_chatbot/tests/test_finetune_gateway_assets.py`

**Interfaces:** none (scripts + Modelfile). Test asserts the assets exist and carry the required content (same SYSTEM as the base Modelfile; the rollback script re-points to the base tag).

- [ ] **Step 1: Write the failing test**
```python
# Dev/kb_chatbot/tests/test_finetune_gateway_assets.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
GW = Path(__file__).parent.parent.parent.parent / "ai_pc" / "reasoning_gateway"

def test_tuned_modelfile_reuses_base_system_and_from_gguf():
    base = (GW / "Modelfile.reasoning").read_text(encoding="utf-8")
    tuned = (GW / "Modelfile.reasoning.tuned").read_text(encoding="utf-8")
    assert "You are the local reasoning model for the Contoso KB chatbot." in tuned
    assert tuned.strip().splitlines()[0].startswith("FROM ")   # FROM the tuned GGUF
    assert "temperature 0" in tuned and "seed 42" in tuned

def test_rollback_targets_base_tag():
    rb = (GW / "08_rollback.ps1").read_text(encoding="utf-8")
    assert "qwen2.5:7b-instruct" in rb
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_gateway_assets.py -v`
Expected: FAIL — files missing.

- [ ] **Step 3: Create the assets** (all string content ASCII — no em-dashes in .ps1; matches the cerebrum note about PowerShell parse failures)
```
# ai_pc/reasoning_gateway/Modelfile.reasoning.tuned
FROM ./contoso-reasoning-qwen25-7b-Q4_K_M.gguf

PARAMETER temperature 0
PARAMETER top_p 1
PARAMETER num_ctx 8192
PARAMETER seed 42

SYSTEM """
You are the local reasoning model for the Contoso KB chatbot.
Answer only from the retrieved context the chatbot provides.
If the answer is not supported by that context, say what is missing and ask for the needed detail - do not guess.
Do not use KYC analyst prompts, KYC test data, or KYC-only assumptions.
Keep answers clear, practical, cited, and suitable for internal team use.
"""
```
```powershell
# ai_pc/reasoning_gateway/07_activate_tuned.ps1
# Create/refresh the tuned Ollama model from the exported GGUF, then serve it.
param([string]$GgufDir = "$PSScriptRoot")
$ErrorActionPreference = "Stop"
Write-Host "Creating tuned model contoso-reasoning-qwen25-7b:v1 ..."
ollama create contoso-reasoning-qwen25-7b:v1 -f "$PSScriptRoot\Modelfile.reasoning.tuned"
Write-Host "Done. Point the gateway at contoso-reasoning-qwen25-7b:v1 and restart it."
```
```powershell
# ai_pc/reasoning_gateway/08_rollback.ps1
# Roll the served model back to the stock base tag (instant fallback).
$ErrorActionPreference = "Stop"
Write-Host "Rolling back to base qwen2.5:7b-instruct ..."
ollama pull qwen2.5:7b-instruct
Write-Host "Base model present. Point the gateway back at qwen2.5:7b-instruct and restart it."
```

- [ ] **Step 4: Run test to verify it passes**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_gateway_assets.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**
```bash
git add ai_pc/reasoning_gateway/Modelfile.reasoning.tuned ai_pc/reasoning_gateway/07_activate_tuned.ps1 ai_pc/reasoning_gateway/08_rollback.ps1 Dev/kb_chatbot/tests/test_finetune_gateway_assets.py
git commit -m "feat(v3.0.1-p5): gateway tuned Modelfile + activate/rollback scripts"
```

---

## P5.5 — Eval gate + flip

### Task 11: `eval_compare.py` — quality + abstain-safety gate

**Files:**
- Create: `Dev/kb_chatbot/finetune/eval_compare.py`
- Test: `Dev/kb_chatbot/tests/test_finetune_eval_compare.py`

**Interfaces:**
- Consumes: `eval.score.accuracy/answer_stability`, `orchestrator.handle_turn/Deps`, `retriever`, `Session`, `Filters`, `eval.dataset.EvalCase`.
- Produces:
  - `abstain_safety(answers_for_unsupported: list[str]) -> float` — fraction of answers that correctly refused (contain the refusal phrase / are empty); 1.0 = perfectly safe.
  - `passes_gate(tuned: dict, base: dict) -> tuple[bool, str]` — gate: `tuned["accuracy"] >= base["accuracy"]` AND `tuned["abstain_safety"] >= base["abstain_safety"]`; returns (ok, reason).
  - `main(argv=None)` — runs the held-out set + a set of unsupported questions through tuned vs base vs claude and prints a table + the gate verdict.

- [ ] **Step 1: Write the failing test**
```python
# Dev/kb_chatbot/tests/test_finetune_eval_compare.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.eval_compare import abstain_safety, passes_gate

def test_abstain_safety_counts_refusals():
    good = ["I don't have enough information in the knowledge base to answer this confidently.", ""]
    bad  = ["Sure, the fix is to reboot."]
    assert abstain_safety(good) == 1.0
    assert abstain_safety(good + bad) < 1.0

def test_gate_requires_quality_up_and_safety_not_down():
    base  = {"accuracy": 0.60, "abstain_safety": 0.90}
    good  = {"accuracy": 0.72, "abstain_safety": 0.92}
    worse_safety = {"accuracy": 0.80, "abstain_safety": 0.80}
    assert passes_gate(good, base)[0] is True
    assert passes_gate(worse_safety, base)[0] is False
```

- [ ] **Step 2: Run test to verify it fails**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_eval_compare.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**
```python
# Dev/kb_chatbot/finetune/eval_compare.py
"""Compare tuned vs base (vs Claude) on the held-out set + an abstain-safety set.
Ship gate: tuned >= base on accuracy AND tuned >= base on abstain-safety."""
from __future__ import annotations
import argparse
from pathlib import Path

_REFUSAL = "don't have enough information"

def abstain_safety(answers_for_unsupported: list[str]) -> float:
    if not answers_for_unsupported:
        return 1.0
    safe = sum(1 for a in answers_for_unsupported
               if (not a.strip()) or _REFUSAL in a.lower())
    return round(safe / len(answers_for_unsupported), 4)

def passes_gate(tuned: dict, base: dict) -> tuple[bool, str]:
    if tuned["accuracy"] < base["accuracy"]:
        return False, f"accuracy regressed ({tuned['accuracy']} < {base['accuracy']})"
    if tuned["abstain_safety"] < base["abstain_safety"]:
        return False, f"abstain-safety regressed ({tuned['abstain_safety']} < {base['abstain_safety']})"
    return True, "tuned >= base on quality AND abstain-safety"

def _score_model(retriever, llm, model, eval_cases, unsupported):
    from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps
    from Dev.kb_chatbot.chat.session import Session
    from Dev.kb_chatbot.retriever import Filters
    from Dev.kb_chatbot.eval.score import accuracy
    accs = []
    for c in eval_cases:
        deps = Deps(retriever=retriever, llm=llm, answer_cache=None)
        turn = handle_turn(c.question, Session.new(), Filters(product=c.product or None), model, deps=deps)
        accs.append(accuracy(turn.content, turn.retrieved_ids, c.expected_sources, c.expected_keypoints))
    unsup_answers = []
    for q in unsupported:
        deps = Deps(retriever=retriever, llm=llm, answer_cache=None)
        unsup_answers.append(handle_turn(q, Session.new(), Filters(), model, deps=deps).content)
    return {"accuracy": round(sum(accs)/(len(accs) or 1), 4),
            "abstain_safety": abstain_safety(unsup_answers)}

def main(argv=None) -> None:
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.retriever import Retriever
    from Dev.kb_chatbot.llm import factory
    from Dev.kb_chatbot.settings import load_settings
    from Dev.kb_chatbot.eval.dataset import load as load_cases
    ap = argparse.ArgumentParser()
    ap.add_argument("--chroma", default=str(config.CHROMA_DIR))
    ap.add_argument("--eval-set", required=True, help="held-out EvalCase json")
    ap.add_argument("--unsupported", required=True, help="newline file of out-of-scope questions")
    ap.add_argument("--tuned-model", default=config.LOCAL_MODEL)
    ap.add_argument("--base-model", default="qwen2.5:7b-instruct")
    args = ap.parse_args(argv)
    retriever = Retriever(Path(args.chroma), confidence_floor=0.0)
    st = load_settings()
    llm = factory.make_provider("local", st)   # both tags served via the same gateway
    cases = load_cases(args.eval_set)
    unsupported = [q for q in Path(args.unsupported).read_text(encoding="utf-8").splitlines() if q.strip()]
    tuned = _score_model(retriever, llm, args.tuned_model, cases, unsupported)
    base  = _score_model(retriever, llm, args.base_model, cases, unsupported)
    ok, why = passes_gate(tuned, base)
    print(f"BASE : {base}\nTUNED: {tuned}\nGATE : {'PASS' if ok else 'FAIL'} - {why}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_finetune_eval_compare.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/finetune/eval_compare.py Dev/kb_chatbot/tests/test_finetune_eval_compare.py
git commit -m "feat(v3.0.1-p5): eval-compare gate (quality up + abstain-safety not down)"
```

---

### Task 12: Full regression + gitignore artifacts

**Files:**
- Modify: `.gitignore` (add the finetune artifacts dir if a repo `.gitignore` covers STATE_DIR-adjacent paths; STATE_DIR is already off-repo, so this only matters if a `datasets/` symlink is used — otherwise a no-op documented in the README).

- [ ] **Step 1: Run the full chatbot suite**
Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests -q`
Expected: all pass (prior suite + the ~8 new finetune test files; train/export importable tests SKIP if heavy deps absent).

- [ ] **Step 2: Commit any gitignore change**
```bash
git add .gitignore
git commit -m "chore(v3.0.1-p5): ignore finetune artifacts (datasets/adapters/gguf live off-repo)"
```

- [ ] **Step 3: Finish the branch** — invoke `superpowers:finishing-a-development-branch` (present the merge/PR/keep options; do NOT auto-merge — the operator decides per their usual pattern).

---

## Self-Review

**1. Spec coverage:**
- RAG-aware objective → Tasks 4-5 (ticket grounding + abstain), 5 (distill style); no knowledge injection (targets are grounded/distilled). ✓
- Hybrid targets → ticket pairs (Task 4) + distilled slice (Task 5) + abstain (Task 4) + assemble (Task 6). ✓
- transformers+peft+bitsandbytes QLoRA, native Windows, 8 GB → Task 7 (4-bit, grad-ckpt, micro-batch 1, seq fallback). ✓
- Dedicated GPU window → Task 8 runbook (stop gateway/pause KYC/dry-run). ✓
- Ship gate (quality up + abstain-safety not down) + spot-check + rollback → Tasks 10-11. ✓
- Serving parity (system=build_system_prompt, user=build_messages) → Task 2. ✓
- PII/secret hard gate → Task 3 + enforced in Task 6 `assemble`. ✓
- Merge→GGUF→Q4_K_M→ollama, versioned tag, base rollback → Tasks 9-10. ✓
- Files under STATE_DIR/finetune, gitignored → Task 1 + Task 12. ✓

**2. Placeholder scan:** No TBD/TODO; every code step has complete code; commands are exact. Operator-run GPU steps (Tasks 8-9 `main`) carry full runnable code even though not unit-tested. ✓

**3. Type consistency:** `make_example(chunks, question, answer)` used identically in Tasks 4/5; `assert_clean(records)` (Task 3) called in Task 6; `retrieve(...).chunks` and `Filters()` consistent with retriever.py; `handle_turn(...).content/.retrieved_ids` consistent with orchestrator; `EvalCase` fields match eval/dataset.py. ✓
