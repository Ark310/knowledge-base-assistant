"""Pure scoring functions for the eval harness (no I/O, deterministic)."""
from __future__ import annotations
from difflib import SequenceMatcher
from itertools import combinations


def accuracy(answer_text: str, retrieved_ids: list[str],
             expected_sources: list[str], expected_keypoints: list[str]) -> float:
    """0..1: half source-recall (were the expected chunks retrieved?), half
    keypoint-coverage (does the answer text mention the expected facts?).
    Source recall gates: 0 expected sources found -> 0.0 overall (a right-sounding
    answer built on the wrong sources is not correct)."""
    if expected_sources:
        found = sum(1 for s in expected_sources if s in set(retrieved_ids))
        src = found / len(expected_sources)
        if found == 0:
            return 0.0
    else:
        src = 1.0
    if expected_keypoints:
        low = (answer_text or "").lower()
        kp = sum(1 for k in expected_keypoints if k.lower() in low) / len(expected_keypoints)
    else:
        kp = 1.0
    return round(0.5 * src + 0.5 * kp, 4)


def source_stability(runs: list[list[str]]) -> float:
    """Mean pairwise Jaccard of the retrieved-id SETS across runs (order-insensitive)."""
    if len(runs) <= 1:
        return 1.0
    sets = [set(r) for r in runs]
    sims = []
    for a, b in combinations(sets, 2):
        union = a | b
        sims.append(1.0 if not union else len(a & b) / len(union))
    return round(sum(sims) / len(sims), 4)


def answer_stability(answers: list[str]) -> float:
    """Mean pairwise text similarity (difflib ratio) across runs."""
    if len(answers) <= 1:
        return 1.0
    sims = [SequenceMatcher(None, a, b).ratio() for a, b in combinations(answers, 2)]
    return round(sum(sims) / len(sims), 4)
