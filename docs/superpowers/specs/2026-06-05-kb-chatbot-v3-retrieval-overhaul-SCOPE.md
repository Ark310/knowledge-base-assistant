# KB Chatbot v3 — Retrieval Overhaul (Scope Notes)

**Status:** Not started — scope notes only. Work happens on branch `dev/kb-chatbot-v3-retrieval-overhaul` in a separate session.

**Context:** v2.4 (in progress on master at time of writing) ships contextual retrieval fusion + escalation LLM query rewriting (Approach B from the 2026-06-05 brainstorm). This branch holds Approach C — the deeper retrieval overhaul — for later evaluation.

## Candidate scope (to be brainstormed in its own session)

1. **Hybrid search** — combine BM25 keyword scoring with the existing vector search (ChromaDB supports neither natively; likely a parallel rank-fusion layer, e.g. Reciprocal Rank Fusion over chromadb + rank-bm25).
2. **Query expansion** — synonym/abbreviation expansion tuned to the Contoso domain (e.g. "deal" ↔ "trade", "post" ↔ "book", product nicknames).
3. **Larger / better reranker** — evaluate bge-reranker-base or similar vs the current ms-marco-MiniLM-L-6-v2; measure accuracy-vs-latency on a golden-question set.
4. **Golden evaluation set** — before any of the above: build a labelled query→article test set from real usage (state/usage.jsonl has every query asked) so changes are measured, not guessed.
5. **Chunk tuning** — revisit 500-word chunks; consider heading-anchored overlap.

## Constraints to carry over

- Accuracy is the top priority; abstention over hallucination.
- Citation format `[Title](url)` validated by URL against retrieved chunks — do not break.
- Offline-capable: models load from local cache; no runtime web dependencies.
- Test env: `scraper\venv\Scripts\python.exe`; suite must stay green.

## Starting points

- Retrieval core: `Dev/kb_chatbot/retriever.py`, `Dev/kb_chatbot/chunker.py`, `Dev/kb_chatbot/ingest.py`
- Usage log for golden set: `Dev/kb_chatbot/state/usage.jsonl`
- v2.3 spec: `docs/superpowers/specs/2026-06-03-kb-chatbot-v2.3-design.md`
