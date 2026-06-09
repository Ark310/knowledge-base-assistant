import math
from Dev.kb_chatbot.retriever import _sigmoid


def test_sigmoid_zero():
    assert abs(_sigmoid(0.0) - 0.5) < 1e-9


def test_sigmoid_monotonic_and_bounded():
    assert _sigmoid(-1.334) < 0.5 < _sigmoid(2.0)
    assert 0.0 < _sigmoid(-12.0) < _sigmoid(11.0) < 1.0


def test_sigmoid_matches_formula():
    for x in (-3.0, -1.334, 0.0, 0.5, 4.0):
        assert abs(_sigmoid(x) - 1 / (1 + math.exp(-x))) < 1e-9
