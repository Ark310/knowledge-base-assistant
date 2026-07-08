"""Canonical query normalization (cache keys) + tokenization (BM25).

normalize() folds trivial rewordings to a stable key so a repeated question
hits the answer cache. tokenize() is the shared BM25 tokenizer for both the
corpus and the query so keyword matching is consistent."""
from __future__ import annotations
import re

from Dev.kb_chatbot import config

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s#]")     # keep word chars, whitespace, and '#'
_TOKEN = re.compile(r"[a-z0-9#]+")


def normalize(query: str) -> str:
    if not query:
        return ""
    q = _PUNCT.sub(" ", query.lower())
    q = _WS.sub(" ", q).strip()
    # Fold product synonyms to their canonical slug (longest name first so
    # "saleshub" is folded before a bare "iq" could ever match).
    for name in sorted(config.PRODUCT_SYNONYM_NAMES, key=len, reverse=True):
        slug = config.resolve_product(name)
        if slug and slug != name:
            q = re.sub(r"\b" + re.escape(name) + r"\b", slug, q)
    return _WS.sub(" ", q).strip()


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())
