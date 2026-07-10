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
