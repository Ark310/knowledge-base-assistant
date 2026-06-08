"""Pick CONFIDENCE_FLOOR for a reranker from a no-gate eval results file.

Usage:
  python -m Dev.kb_chatbot.eval.calibrate_floor --results eval/results/rerank-bge-large.json

Sweeps thresholds over observed rerank_top_score values; recommends the floor
maximizing F1 of 'abstain on junk' (positive class = must_abstain abstained,
false positive = answerable abstained)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def best_floor(rows: list[dict]) -> tuple[float, float]:
    answerable = [r["rerank_top_score"] for r in rows if r["kind"] == "answerable"]
    junk = [r["rerank_top_score"] for r in rows if r["kind"] == "must_abstain"]
    candidates = sorted(set(answerable + junk))
    best = (float("-inf"), 0.0)  # (floor, f1)
    for t in candidates:
        tp = sum(1 for s in junk if s < t)          # junk correctly gated
        fp = sum(1 for s in answerable if s < t)    # answerable wrongly gated
        fn = len(junk) - tp
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        if f1 > best[1]:
            best = (t, f1)
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    args = ap.parse_args()
    rows = json.loads(args.results.read_text(encoding="utf-8"))["rows"]
    floor, f1 = best_floor(rows)
    print(f"recommended CONFIDENCE_FLOOR = {floor:.4f}  (abstain F1 = {f1:.3f})")


if __name__ == "__main__":
    main()
