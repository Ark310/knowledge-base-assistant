"""Persistent answer cache: identical answer for a repeated standalone question.

Keyed on (normalized query, product filter, model, index version). Only the
already-scrubbed, citation-validated answer payload is stored (no raw ticket
text / PII). Insertion-ordered JSON; oldest entries evicted past max_entries."""
from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from Dev.kb_chatbot import config

log = logging.getLogger("kb_chatbot.answer_cache")


def make_key(normalized_query: str, product: str, model: str) -> str:
    base = f"{normalized_query}|{product or ''}|{model}|{config.INDEX_VERSION}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


class AnswerCache:
    def __init__(self, path: Path, max_entries: int = config.ANSWER_CACHE_MAX):
        self.path = Path(path)
        self.max_entries = max_entries
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    self._data = d
            except Exception:
                log.warning("Answer cache unreadable; starting empty")
                self._data = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data), encoding="utf-8")
        except Exception as exc:
            log.warning("Answer cache save failed: %s", exc)

    def get(self, key: str) -> Optional[dict]:
        return self._data.get(key)

    def put(self, key: str, payload: dict) -> None:
        if key in self._data:
            del self._data[key]           # move-to-end (refresh recency)
        self._data[key] = payload
        while len(self._data) > self.max_entries:
            oldest = next(iter(self._data))
            del self._data[oldest]
        self._save()
