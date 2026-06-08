"""Retrieval eval harness. Dev-only — never bundled into the exe.

Usage:
  python -m Dev.kb_chatbot.eval.run_eval --chroma <dir> --label baseline \
      [--golden <path>] [--no-bm25] [--no-expansion] [--reranker <model>] [--floor <f>]

Metrics: recall@8 (article url in chunks handed to the LLM), MRR,
abstain precision/recall on must_abstain cases, p50/p95 latency.
Writes JSON to eval/results/<label>.json and prints a summary table."""
from __future__ import annotations
import argparse
import json
import statistics
import time
from pathlib import Path

from Dev.kb_chatbot import config
from Dev.kb_chatbot.eval.metrics import mrr, recall_at_k, unique_article_urls
from Dev.kb_chatbot.retriever import Filters, Retriever

HERE = Path(__file__).parent


def load_golden(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def run(retriever: Retriever, golden: list[dict], k: int) -> dict:
    rows, latencies = [], []
    for case in golden:
        t0 = time.perf_counter()
        result = retriever.retrieve(case["query"], Filters())
        ms = (time.perf_counter() - t0) * 1000
        latencies.append(ms)
        urls = unique_article_urls(result.chunks)
        rows.append({
            "query": case["query"],
            "kind": case["kind"],
            "tag": case.get("tag"),
            "abstained": result.abstain_reason is not None,
            "hit": recall_at_k(urls, case["expected_urls"], k) if case["kind"] == "answerable" else None,
            "mrr": mrr(urls, case["expected_urls"]) if case["kind"] == "answerable" else None,
            "rerank_top_score": result.rerank_top_score,
            "latency_ms": round(ms, 1),
        })
    answerable = [r for r in rows if r["kind"] == "answerable"]
    junk = [r for r in rows if r["kind"] == "must_abstain"]
    abstained_junk = sum(1 for r in junk if r["abstained"])
    abstained_ans = sum(1 for r in answerable if r["abstained"])
    return {
        "cases": len(rows),
        f"recall@{k}": round(sum(1 for r in answerable if r["hit"]) / max(len(answerable), 1), 4),
        "mrr": round(statistics.mean(r["mrr"] for r in answerable) if answerable else 0.0, 4),
        "abstain_recall_on_junk": round(abstained_junk / max(len(junk), 1), 4),
        "false_abstain_on_answerable": round(abstained_ans / max(len(answerable), 1), 4),
        "p50_latency_ms": round(statistics.median(latencies), 1),
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 1),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chroma", type=Path, required=True)
    ap.add_argument("--golden", type=Path, default=HERE / "golden.jsonl")
    ap.add_argument("--label", required=True)
    ap.add_argument("--k", type=int, default=config.TOP_K_RERANK)
    ap.add_argument("--no-bm25", action="store_true")
    ap.add_argument("--no-expansion", action="store_true")
    ap.add_argument("--reranker", default=config.RERANKER_MODEL)
    ap.add_argument("--floor", type=float, default=config.CONFIDENCE_FLOOR)
    args = ap.parse_args()

    retriever = Retriever(
        args.chroma,
        confidence_floor=args.floor,
        use_bm25=not args.no_bm25,
        use_expansion=not args.no_expansion,
        reranker_model=args.reranker,
    )
    try:
        summary = run(retriever, load_golden(args.golden), args.k)
    finally:
        retriever.close()

    summary["config"] = {
        "bm25": not args.no_bm25, "expansion": not args.no_expansion,
        "reranker": args.reranker, "floor": args.floor, "k": args.k,
    }
    out = HERE / "results" / f"{args.label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    for key in (f"recall@{args.k}", "mrr", "abstain_recall_on_junk",
                "false_abstain_on_answerable", "p50_latency_ms", "p95_latency_ms"):
        print(f"{key:32s} {summary[key]}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
