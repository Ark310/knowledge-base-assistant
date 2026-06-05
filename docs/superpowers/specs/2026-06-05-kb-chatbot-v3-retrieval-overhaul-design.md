# KB Chatbot v3 — Retrieval Overhaul (Approach C) — Design

**Date:** 2026-06-05
**Branch:** `dev/kb-chatbot-v3-retrieval-overhaul` (based on v2.3, commit 55791b6)
**Status:** Approved design — supersedes the scope notes in `2026-06-05-kb-chatbot-v3-retrieval-overhaul-SCOPE.md`
**Deliverable:** `dist\ContosoKBChatbot-BETA.exe` — a separately named, separately stated beta that coexists with the stable v2.3 exe in the same `dist\` folder without overwriting anything.

## Decisions (from brainstorm)

| Question | Decision |
|---|---|
| Scope | Full Approach C: golden eval set, hybrid search, query expansion, reranker upgrade, chunk tuning |
| Base | v2.3 (as branched). v2.4's Approach B is merged later, separately — this beta measures Approach C in isolation |
| Beta identity | `ContosoKBChatbot-BETA.exe`, own `chatbot_state_beta\` state dir, window title shows "v3.0 BETA" |
| Golden set | ~15 real queries from `dist\chatbot_state\usage.jsonl` seeds + ~80–100 authored cases; user spot-reviews |
| Size/latency budget | Accuracy at any cost — strongest offline reranker that works, exe may approach ~2 GB |
| Architecture | Layered retrieval pipeline (Approach 1 of 3 considered; hybrid-native store migration and minimal bolt-on rejected) |

## Architecture

### Module layout

```
Dev/kb_chatbot/
  retriever.py          # orchestrator of the stages below
  lexical.py            # NEW — BM25 index: build/persist/load/query (rank-bm25)
  fusion.py             # NEW — Reciprocal Rank Fusion (pure function)
  expansion.py          # NEW — synonym expansion from a static YAML map
  data/synonyms.yaml    # NEW — Contoso domain map (deal↔trade, post↔book, product nicknames)
  chunker.py            # gains optional overlap_words param
  ingest.py             # builds BM25 index in the same pass as chroma
  eval/
    golden.jsonl        # labelled query→article golden set
    run_eval.py         # dev-only CLI harness (NOT bundled in exe)
    results/            # timestamped run outputs
    workspace/          # throwaway chroma dirs for chunk-variant experiments
```

### Query-time data flow (`Retriever.retrieve()`)

```
query ──┬─ embed → chroma vector search ──────────────┐
        └─ expand (synonyms) → BM25 keyword search ───┴─ RRF fuse
                                                          ↓
                                          cross-encoder rerank (bge family)
                                                          ↓
                                  confidence floor gate → chunks OR abstain
```

### Key decisions

- **Fusion happens before the rerank + confidence gate.** The existing abstention and citation contracts (`[Title](url)` validated against retrieved chunks) are untouched; downstream code sees the same `RetrievalResult`.
- **BM25 is a sidecar, never a second source of truth.** Ingest pickles the BM25 index next to chroma, stamped with a corpus hash. At startup the retriever checks the stamp; on mismatch/missing it rebuilds the index from chroma's own documents (tokenization only, seconds). The two indexes structurally cannot drift apart.
- **Expansion only touches the BM25 query.** The vector query stays raw — embeddings already handle soft synonymy; the map fixes exact-keyword misses.
- **Reranker** swaps via `config.RERANKER_MODEL` to the bge-reranker candidate that wins on the golden set (`bge-reranker-large` / `bge-reranker-v2-m3` are candidates). bge scores are on a different scale than ms-marco, so `CONFIDENCE_FLOOR` is recalibrated on the golden set plus known-junk queries that must still abstain.
- **Stage toggles in config** so the eval harness can A/B any single stage.

## Golden eval set & harness

### Golden set — `Dev/kb_chatbot/eval/golden.jsonl`

One labelled case per line:

```json
{"query": "how do I book a corporate deal", "expected_urls": ["https://help.contoso.example/..."], "product": "tradedesk", "kind": "answerable"}
{"query": "what's the weather in Toronto", "expected_urls": [], "kind": "must_abstain"}
```

- Seeded from the ~15 answered queries in `dist\chatbot_state\usage.jsonl`, labelled with the article they actually cited, verified by hand.
- Augmented to ~80–100 authored cases drawn from real KB article content across all six products: paraphrases, domain-synonym phrasings (the exact cases expansion should fix), version-specific questions, and ~10 `must_abstain` junk/out-of-domain queries to calibrate the floor.
- User spot-reviews the set before it becomes the gate (lands as a normal file in the PR).

### Harness — `Dev/kb_chatbot/eval/run_eval.py`

Dev-only CLI (runs in `scraper\venv`, not bundled into the exe):

- **Metrics:** recall@8 (expected article present in the chunks handed to the LLM — the primary number), MRR, abstain precision/recall on junk queries, p50/p95 retrieval latency.
- **Stage toggles:** `--no-bm25`, `--no-expansion`, `--reranker <model>`, `--chunk-variant <name>` — every Approach C claim gets a before/after table.
- **Output:** `Dev/kb_chatbot/eval/results/<timestamp>-<label>.json` so runs are comparable across the branch's life.
- **Baseline first:** the harness's run against unmodified v2.3 retrieval is the first committed result. Nothing else lands until that number exists.

## Chunk tuning

`chunker.py` gains `overlap_words` (tail of previous chunk prepended to the next); the existing heading-anchor behavior is made explicit. Variants are ingested into throwaway chroma dirs under `eval/workspace/` and compared via the harness. Shipped chunking changes only if a variant beats the 500-word baseline on recall@8; otherwise v3 ships current chunking and the results table documents why.

## Beta packaging & isolation

All beta identity lives on this branch only — stable code never sees it:

- `config.py`: `APP_VERSION = "3.0.0-beta"`, `IS_BETA = True`. When frozen, `STATE_DIR = <exe folder>\chatbot_state_beta` (instead of `chatbot_state`).
- `gui.py` window title: **"Contoso KB Chatbot — v3.0 BETA"**.
- New `ContosoKBChatbot-BETA.spec`: cloned from the current spec, `name="ContosoKBChatbot-BETA"`, with bge reranker and embedder weights bundled into datas so offline works on any machine (no HF cache dependency). This is where the accepted size budget goes.
- New `build_chatbot_beta_exe.bat` passing `--distpath` at the existing `dist\` folder (build runs from the worktree).

**Nothing in `dist\` is overwritten:** PyInstaller `--clean` only clears its own build cache; the output name differs, so the result is exactly `dist\ContosoKBChatbot-BETA.exe` plus a fresh `dist\chatbot_state_beta\` created on first run. The stable exe, its state, and the library are untouched. First beta launch runs the existing ingest flow against `dist\library\kb` to build its own index — expected behavior.

**Workspace:** implementation happens in the git worktree `.claude\worktrees\kb-chatbot-v3` so the in-progress v2.4 checkout stays untouched.

## Error handling (no silent failures)

| Failure | Behavior |
|---|---|
| BM25 pickle missing/stale | Rebuild from chroma docs at startup (seconds); log it |
| Rebuild also fails | Vector-only retrieval + visible warning in status bar + log |
| `synonyms.yaml` malformed | Skip expansion, log warning — never crash retrieval |
| Reranker weights missing | Fail fast at the existing startup preflight with a clear message |

## Testing

- TDD per stage: unit tests for `lexical`, `fusion`, `expansion`, chunker overlap.
- Integration test asserting the citation/abstention contract is unchanged (same `RetrievalResult` shape, URL-validated citations, abstain on junk).
- Full suite green in `scraper\venv` before any build.
- Acceptance evidence for the beta: the golden-set baseline-vs-final results table.

## Constraints carried over (from scope notes)

- Accuracy is the top priority; abstention over hallucination.
- Citation format `[Title](url)` validated by URL against retrieved chunks — do not break.
- Offline-capable: no runtime web dependencies; beta bundles model weights in the exe.
- Test env: `scraper\venv\Scripts\python.exe`; suite must stay green.
