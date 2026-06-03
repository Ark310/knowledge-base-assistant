"""V2.3 citations: parse + validate [Title](url) citation form."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import List

from Dev.kb_chatbot.chunker import Chunk

log = logging.getLogger("kb_chatbot.citations")

# Matches [Title](https://...)
_CITE_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")


@dataclass
class Citation:
    raw: str
    title: str
    url: str


@dataclass
class ValidationResult:
    all_verified: bool
    stripped_text: str
    verified: list[Citation] = field(default_factory=list)
    unverified: list[Citation] = field(default_factory=list)


def parse_citations(text: str) -> List[Citation]:
    out = []
    for m in _CITE_RE.finditer(text):
        out.append(Citation(
            raw=m.group(0),
            title=m.group(1).strip(),
            url=m.group(2).strip(),
        ))
    return out


def _matches(cite: Citation, chunk: Chunk) -> bool:
    return cite.url == chunk.metadata.get("url", "")


def validate(answer: str, retrieved: list[Chunk]) -> ValidationResult:
    cites = parse_citations(answer)
    verified, unverified = [], []
    for c in cites:
        if any(_matches(c, ch) for ch in retrieved):
            verified.append(c)
        else:
            unverified.append(c)
            log.warning("Unverified citation: %s", c.raw)

    stripped = answer
    for u in unverified:
        stripped = stripped.replace(u.raw, "[unverified]")

    return ValidationResult(
        all_verified=len(unverified) == 0,
        stripped_text=stripped,
        verified=verified,
        unverified=unverified,
    )
