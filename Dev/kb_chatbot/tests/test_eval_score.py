import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.eval.score import accuracy, source_stability, answer_stability


def test_accuracy_full_when_sources_and_keypoints_present():
    a = accuracy("The buy amount was null; fixed in the DB. [Ticket #75919](u)",
                 retrieved_ids=["ticket_1"],
                 expected_sources=["ticket_1"],
                 expected_keypoints=["buy amount", "null"])
    assert a == 1.0

def test_accuracy_partial_when_keypoint_missing():
    a = accuracy("Something unrelated. [Ticket #75919](u)",
                 retrieved_ids=["ticket_1"],
                 expected_sources=["ticket_1"],
                 expected_keypoints=["buy amount", "null"])
    assert 0.0 < a < 1.0

def test_accuracy_zero_when_source_missing():
    a = accuracy("text", retrieved_ids=["other"], expected_sources=["ticket_1"],
                 expected_keypoints=[])
    assert a == 0.0

def test_source_stability_identical_runs_is_one():
    assert source_stability([["a", "b"], ["b", "a"], ["a", "b"]]) == 1.0

def test_source_stability_varying_runs_below_one():
    assert source_stability([["a", "b"], ["a", "c"]]) < 1.0

def test_answer_stability_identical_is_one():
    assert answer_stability(["same text", "same text"]) == 1.0

def test_answer_stability_different_below_one():
    assert answer_stability(["the cat sat", "a dog ran"]) < 1.0

def test_stability_single_run_is_one():
    assert source_stability([["a"]]) == 1.0
    assert answer_stability(["only"]) == 1.0
