"""Reciprocal Rank Fusion of multiple ranked id lists. Pure function, no I/O."""
from __future__ import annotations


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Fuse ranked lists of ids via RRF: score(id) = Σ 1/(k + rank + 1).

    Higher fused score ranks first; ties break alphabetically by id so
    results are deterministic across runs."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return [cid for cid, _ in sorted(scores.items(), key=lambda t: (-t[1], t[0]))]
