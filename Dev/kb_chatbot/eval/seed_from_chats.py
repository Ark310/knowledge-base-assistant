"""Extract golden-set seed candidates from saved chat sessions.

Usage:
  python -m Dev.kb_chatbot.eval.seed_from_chats --chats <dir> [--out seeds.jsonl]

Each user turn followed by an assistant turn with verified citations becomes a
candidate: {"query": ..., "cited_titles": [...], "expected_urls": [], "kind": "answerable"}.
Citations carry titles, not URLs, so expected_urls starts empty and is filled
by hand against library/kb (the seed output is a worksheet, not the gate)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def extract(chats_dir: Path) -> list[dict]:
    seeds: list[dict] = []
    for f in sorted(chats_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        turns = data.get("turns", [])
        for i, turn in enumerate(turns[:-1]):
            nxt = turns[i + 1]
            if turn.get("role") != "user" or nxt.get("role") != "assistant":
                continue
            citations = [c.get("raw", "") for c in (nxt.get("citations") or []) if c.get("verified")]
            if not citations:
                continue
            seeds.append({
                "query": turn.get("content", "").strip(),
                "cited_titles": sorted(set(citations)),
                "expected_urls": [],
                "kind": "answerable",
                "source": f.name,
            })
    return seeds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chats", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "seeds.jsonl")
    args = ap.parse_args()
    seeds = extract(args.chats)
    with open(args.out, "w", encoding="utf-8") as fh:
        for s in seeds:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"{len(seeds)} seed candidates -> {args.out}")


if __name__ == "__main__":
    main()
