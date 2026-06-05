import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.fusion import rrf_fuse


def test_item_in_both_rankings_beats_item_in_one():
    fused = rrf_fuse([["a", "b", "c"], ["b", "d"]])
    assert fused[0] == "b"          # appears in both lists
    assert set(fused) == {"a", "b", "c", "d"}


def test_preserves_order_within_single_ranking():
    assert rrf_fuse([["x", "y", "z"]]) == ["x", "y", "z"]


def test_empty_rankings_return_empty():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_deterministic_tie_break_by_id():
    # 'a' and 'b' get identical scores (same rank, disjoint lists) → sorted by id
    assert rrf_fuse([["b"], ["a"]]) == ["a", "b"]


def test_k_parameter_dampens_rank_differences():
    # With huge k, rank position barely matters; doc in two lists still wins
    fused = rrf_fuse([["a", "b"], ["c", "b"]], k=10_000)
    assert fused[0] == "b"
