"""V2.2 citations: parse + validate the article-based citation form [Product · Category · Title]."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import List

from Dev.kb_chatbot.chunker import Chunk

log = logging.getLogger("kb_chatbot.citations")

_CITE_RE = re.compile(
    r"\["
    r"(?P<product>API|TradeDesk|SalesHub|Web2|Web4|Other)"
    r"\s+·\s+"
    r"(?P<category>[^\]·]+?)"
    r"\s+·\s+"
    r"(?P<title>[^\]]+?)"
    r"\]"
)

_PRODUCT_NORMAL = {
    "API": "api", "TradeDesk": "tradedesk", "SalesHub": "saleshub",
    "Web2": "web2", "Web4": "web4", "Other": "other",
}


@dataclass
class Citation:
    raw: str
    product: str
    category: str
    title: str


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
            product=m.group("product"),
            category=m.group("category").strip(),
            title=m.group("title").strip(),
        ))
    return out


def _matches(cite: Citation, chunk: Chunk) -> bool:
    md = chunk.metadata
    if _PRODUCT_NORMAL.get(cite.product) != md.get("product"):
        return False
    md_cat = (md.get("category") or "").strip().lower() or "general"
    if cite.category.strip().lower() != md_cat:
        return False
    return cite.title.strip() == md.get("title", "").strip()


def validate(answer: str, retrieved: list[Chunk]) -> ValidationResult:
    cites = parse_citations(answer)
    verified, unverified = [], []
    for c in cites:
        if any(_matches(c, ch) for ch in retrieved):
            verified.append(c)
        else:
            unverified.append(c)
            log.warning("Hallucinated citation: %s", c.raw)

    stripped = answer
    for u in unverified:
        stripped = stripped.replace(u.raw, "[unverified]")

    return ValidationResult(
        all_verified=len(unverified) == 0,
        stripped_text=stripped,
        verified=verified,
        unverified=unverified,
    )
