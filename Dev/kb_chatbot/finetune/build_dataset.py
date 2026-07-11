"""Assemble the fine-tuning JSONL: ticket problem->resolution pairs (grounding),
abstain/safety examples, and (merged in main) the distilled style slice. Every
example is redaction-gated before it is written."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Iterator

from Dev.kb_chatbot.finetune import finetune_config as fc
from Dev.kb_chatbot.finetune.example_format import make_example, dumps, loads
from Dev.kb_chatbot.finetune.redaction import assert_clean, scrub_records
import logging
from Dev.kb_chatbot.ticket_ingest import _known_terms, _problem_text, _resolution_text
log = logging.getLogger("kb_chatbot.finetune.build_dataset")
from Dev.kb_chatbot.retriever import Filters

# Exact refusal from prompt.py rule 2 — the abstain target the model must learn.
ABSTAIN_TEXT = ("I don't have enough information in the knowledge base to answer "
                "this confidently.")

def ticket_target(resolution: str, ticket_id: str, url: str) -> str:
    cite = f"[Ticket #{ticket_id}]({url})" if url else f"[Ticket #{ticket_id}]"
    return f"{resolution}\n\nSources: {cite}"

def _iter_ticket_json(tickets_dir: Path) -> Iterator[dict]:
    for fp in sorted(tickets_dir.glob("ticket_*.json")):
        try:
            yield json.loads(fp.read_text(encoding="utf-8")), fp
        except Exception as exc:
            log.warning("skipping unreadable ticket %s: %s", fp.name, type(exc).__name__)
            continue

def ticket_examples(retriever, tickets_dir: Path, limit: int) -> Iterator[dict]:
    n = 0
    scanned = 0
    t0 = time.time()
    for data, fp in _iter_ticket_json(Path(tickets_dir)):
        if n >= limit:
            break
        scanned += 1
        if scanned % 500 == 0:   # liveness: many tickets get skipped (no resolution)
            print(f"[dataset]   scanned {scanned} tickets -> {n} examples "
                  f"({(time.time() - t0) / 60:.1f}m)", flush=True)
        known = _known_terms(data)
        problem = _problem_text(data, known)
        resolution = _resolution_text(data, known)
        if not problem or not resolution:      # resolved == bool(resolution)
            continue
        ctx = retriever.retrieve(problem, Filters(), top_k_rerank=None).chunks
        answer = ticket_target(resolution, str(data.get("ticket_id", "")),
                               data.get("url", "") or data.get("resolution_url", ""))
        yield make_example(ctx, problem, answer)
        n += 1

def abstain_examples(retriever, questions: list[str]) -> Iterator[dict]:
    for q in questions:
        ctx = retriever.retrieve(q, Filters(), top_k_rerank=None).chunks
        # Teach refusal even when a few weak chunks came back: target is the refusal.
        yield make_example(ctx, q, ABSTAIN_TEXT)


import random

def assemble(ticket_recs, abstain_recs, distill_recs, holdout: int, rng_seed: int = 42):
    records = list(ticket_recs) + list(abstain_recs) + list(distill_recs)
    scrub_records(records)                      # neutralize benign business emails / any PII in context
    assert_clean(records)                       # backstop: raises if anything PII-shaped survived
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

    print(f"[dataset] loading retriever from {args.chroma} ...", flush=True)
    retriever = Retriever(Path(args.chroma), confidence_floor=0.0)
    print(f"[dataset] building ticket examples from {args.tickets} "
          f"(cap {fc.MAX_TICKET_EXAMPLES}) ...", flush=True)
    tickets = list(ticket_examples(retriever, Path(args.tickets), fc.MAX_TICKET_EXAMPLES))
    print(f"[dataset] ticket examples: {len(tickets)}", flush=True)

    ab_qs = (Path(args.abstain_questions).read_text(encoding="utf-8").splitlines()
             if args.abstain_questions else [])[:fc.ABSTAIN_EXAMPLES]
    abstain = list(abstain_examples(retriever, ab_qs))
    print(f"[dataset] abstain examples: {len(abstain)}", flush=True)

    distill = [loads(l) for l in fc.DISTILL_JSONL.read_text(encoding="utf-8").splitlines()] \
        if fc.DISTILL_JSONL.exists() else []
    print(f"[dataset] distilled examples loaded: {len(distill)}", flush=True)

    print("[dataset] running PII/secret redaction gate on all records ...", flush=True)
    train, ev = assemble(tickets, abstain, distill, holdout=fc.EVAL_HOLDOUT)
    print("[dataset] redaction gate PASSED.", flush=True)
    _write(fc.TRAIN_JSONL, train)
    _write(fc.EVAL_JSONL, ev)
    print(f"[dataset] DONE  train={len(train)} eval={len(ev)}  "
          f"({len(tickets)} ticket, {len(abstain)} abstain, {len(distill)} distilled)", flush=True)
    print(f"[dataset] wrote {fc.TRAIN_JSONL}", flush=True)

if __name__ == "__main__":
    main()
