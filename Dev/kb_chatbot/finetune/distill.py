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
