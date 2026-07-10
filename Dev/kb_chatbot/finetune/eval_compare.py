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
