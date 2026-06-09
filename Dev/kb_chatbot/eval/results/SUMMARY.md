# v3 Retrieval Overhaul — Golden Set Results

**Golden set:** 97 cases (87 answerable, 10 must-abstain), grounded in real
`library/kb` article URLs (`golden.jsonl`). recall@8 = the expected article's
URL is among the chunks handed to the LLM. Latency is end-to-end per query on a
4-thread CPU (no GPU), reranking the full fused candidate union.

| run | chunking | reranker | recall@8 | MRR | junk-abstain | false-abstain | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|
| baseline-v2.3 (vector only) | 500w | ms-marco-MiniLM | 0.816 | 0.630 | 0.90 | 0.092 | 2 875 | 3 534 |
| hybrid (+BM25 +expansion) | 500w | ms-marco-MiniLM | 0.816 | 0.645 | 0.90 | 0.092 | 3 918 | 5 149 |
| reranker swap (gate off) | 500w | bge-reranker-base | 0.908 | 0.705 | n/a¹ | n/a¹ | 23 909 | 31 388 |
| reranker gated | 500w | bge-reranker-base | 0.908 | 0.705 | 0.80 | 0.000 | 25 991 | 34 605 |
| **shipped (chunk overlap 80)** | **500w +80 overlap** | **bge-reranker-base** | **0.920** | **0.760** | **0.80** | **0.000** | **33 785** | **51 175** |

¹ Gate disabled (`--floor -99`) to measure pure ranking quality, so abstain metrics don't apply.

**Net vs baseline:** recall@8 **0.816 → 0.920** (+10.4 pts), MRR **0.630 → 0.760**
(+0.130), and false-abstain on real questions **0.092 → 0.000** (the bge floor at
0.05 never gates a genuine answer). Cost: per-query latency rose from ~3 s to
~34 s p50 (the bge cross-encoder reranks the full vector+BM25 union on CPU) — the
accepted trade under the "accuracy at any cost" directive.

## Shipped configuration

- **Hybrid retrieval:** vector (ChromaDB, all-MiniLM-L6-v2) + BM25 sidecar
  (rank-bm25), synonym-expanded on the BM25 query only, fused by Reciprocal Rank
  Fusion (k=60), reranking the **full** fused union (no pre-rerank truncation).
- **Reranker:** `BAAI/bge-reranker-base` (0–1 sigmoid scores).
- **Confidence floor:** 0.05 (calibrated on the golden set: gates 8/10 junk, 0
  real answers). `CLARIFY_SCORE_FLOOR` 0.01 on the same scale.
- **Chunking:** 500-word target with 80-word overlap (`[…]` tail prepended).

## Notes / decisions

- **bge-reranker-large and bge-reranker-v2-m3 were NOT benchmarked.** After
  bge-reranker-base delivered +9.2 pts recall@8 at ~24 s/query, the larger
  candidates (~2× slower, ~1 hr+ CPU each to benchmark) were skipped by explicit
  user decision in favour of base's accuracy/latency balance.
- A fusion-truncation bug was found via this harness: truncating the RRF union to
  `top_k_retrieve` before reranking dropped vector hits that BM25 had displaced
  past rank 30. Reranking the full union fixed it (restored hybrid recall to
  baseline and enabled the bge gain). Regression test added.
- The `must_abstain` junk-recall ceiling is 0.80 because 2 of 10 out-of-domain
  queries match a real article strongly enough (bge score 0.86 / 0.99) that no
  floor can gate them without also killing real answers.

## Beta build

- **Artifact:** `dist\ContosoKBChatbot-BETA.exe` (~1.68 GB onefile), built from
  `ContosoKBChatbot-BETA.spec` via `build_chatbot_beta_exe.bat`. Bundles the bge
  reranker, the embedder, and the synonyms map for offline use.
- **No overwrite:** the stable `dist\ContosoKBChatbot.exe` is byte-identical
  before and after the build; the beta is a separate, differently-named artifact
  with its own `dist\chatbot_state_beta\` state dir.
- **Runtime smoke test (passed):** the frozen exe starts cleanly, loads both
  bundled models from `_MEIPASS\models\...` (no network), boots the bundled
  Claude CLI (haiku), rebuilds the BM25 sidecar without error, and creates
  `chatbot_state_beta\` while leaving the stable `chatbot_state\` untouched.
- **Full test suite:** 185 passed (148 chatbot + 37 scraper).
- **Manual GUI check left for the operator:** confirm the title bar reads
  "Contoso KB Chatbot — v3.0 BETA", run Reindex against `dist\library\kb`, ask a
  known question (expect an answer + citation) and an out-of-domain one (expect
  abstain). First launch unpacks ~2 GB, so allow ~1 min before the window is ready.
- **Known cosmetic issue:** a couple of v3 log lines use an em-dash/arrow that
  renders as mojibake in `run.log` under the default Windows file encoding —
  readability only, no functional impact.
