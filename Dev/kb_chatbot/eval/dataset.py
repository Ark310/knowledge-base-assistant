"""Eval-case model + loader."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalCase:
    question: str
    product: str = ""                       # optional product filter
    expected_sources: list[str] = field(default_factory=list)      # chunk ids or ticket_ids
    expected_keypoints: list[str] = field(default_factory=list)    # substrings the answer should contain


def load(path) -> list[EvalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvalCase(**c) for c in data]
