"""Batched scraped-tickets state (v4.0.3).

v4.0.2 rewrote the full ~50KB OneDrive-synced scraped_tickets.json after EVERY
saved ticket. Now saves append one line to a `.journal` sidecar (cheap, atomic
enough) and the full JSON is compacted every `every` marks or `interval`
seconds, at flush(), and on journal replay after a crash — a hard kill loses
nothing (load() replays the journal).
"""
from __future__ import annotations
import json
import time
from pathlib import Path


class ScrapedState:
    def __init__(self, state_file: Path | None = None, *,
                 every: int = 25, interval: float = 10.0, clock=time.monotonic):
        if state_file is None:
            from scraper.ticket_engine import TICKET_STATE_FILE
            state_file = TICKET_STATE_FILE
        self._file = Path(state_file)
        self._journal = self._file.with_name(self._file.name + ".journal")
        self._every, self._interval, self._clock = max(1, every), interval, clock
        self.ids: set[str] = set()
        self._unflushed = 0
        self._last_compact = clock()

    def load(self) -> set[str]:
        ids: set[str] = set()
        try:
            if self._file.exists():
                ids = set(json.loads(self._file.read_text(encoding="utf-8")))
        except Exception:
            ids = set()
        replayed = False
        try:
            if self._journal.exists():
                extra = [ln for ln in self._journal.read_text(encoding="utf-8").split()
                         if ln.strip()]
                replayed = bool(extra)
                ids.update(extra)
        except Exception:
            pass
        self.ids = ids
        if replayed:
            self._compact()
        return self.ids

    def mark(self, tid: str) -> None:
        tid = str(tid)
        if tid in self.ids:
            return
        self.ids.add(tid)
        try:
            self._journal.parent.mkdir(parents=True, exist_ok=True)
            with self._journal.open("a", encoding="utf-8") as f:
                f.write(tid + "\n")
        except Exception:
            pass
        self._unflushed += 1
        if (self._unflushed >= self._every
                or self._clock() - self._last_compact >= self._interval):
            self._compact()

    def flush(self) -> None:
        self._compact()

    def _compact(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(sorted(self.ids), indent=2),
                                  encoding="utf-8")
            self._journal.write_text("", encoding="utf-8")
        except Exception:
            return
        self._unflushed = 0
        self._last_compact = self._clock()
