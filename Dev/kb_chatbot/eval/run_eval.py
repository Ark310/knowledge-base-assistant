"""Run the eval set through the orchestrator K times per case and report
accuracy + consistency. Live providers are selected by name; use 'fake' only
for a wiring smoke test.

Usage:
  python -m Dev.kb_chatbot.eval.run_eval --chroma <path> --provider claude --model claude-sonnet-4-6 --runs 3
"""
from __future__ import annotations
import argparse
from pathlib import Path

from Dev.kb_chatbot.eval.dataset import load
from Dev.kb_chatbot.eval.score import accuracy, source_stability, answer_stability


def _make_llm(provider: str):
    if provider == "fake":
        from Dev.kb_chatbot.llm.fake_provider import FakeProvider
        return FakeProvider(canned_text="stub answer")
    if provider == "claude":
        from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider
        return ClaudeCodeProvider()
    if provider == "openai":
        from Dev.kb_chatbot.llm.codex_provider import CodexProvider
        return CodexProvider()
    raise SystemExit(f"unknown provider: {provider}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chroma", required=True)
    ap.add_argument("--provider", default="fake")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--set", default=str(Path(__file__).parent / "eval_set.json"))
    args = ap.parse_args()

    from Dev.kb_chatbot.retriever import Retriever, Filters
    from Dev.kb_chatbot.chat.session import Session
    from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps

    retriever = Retriever(Path(args.chroma), confidence_floor=0.0)
    llm = _make_llm(args.provider)
    cases = load(args.set)

    acc_total = src_total = ans_total = 0.0
    for case in cases:
        runs_ids: list[list[str]] = []
        runs_text: list[str] = []
        for _ in range(args.runs):
            deps = Deps(retriever=retriever, llm=llm)   # no cache: measure raw model consistency
            turn = handle_turn(case.question, Session.new(),
                               Filters(product=case.product or None), args.model, deps=deps)
            runs_ids.append(turn.retrieved_ids)
            runs_text.append(turn.content)
        acc = accuracy(runs_text[0], runs_ids[0], case.expected_sources, case.expected_keypoints)
        s_src = source_stability(runs_ids)
        s_ans = answer_stability(runs_text)
        acc_total += acc; src_total += s_src; ans_total += s_ans
        print(f"[{acc:.2f} acc | {s_src:.2f} src-stable | {s_ans:.2f} ans-stable] {case.question[:60]}")

    n = len(cases) or 1
    print(f"\nMEANS  accuracy={acc_total/n:.3f}  source_stability={src_total/n:.3f}  "
          f"answer_stability={ans_total/n:.3f}  (provider={args.provider} model={args.model} runs={args.runs})")


if __name__ == "__main__":
    main()
