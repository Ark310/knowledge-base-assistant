"""Journaled KB article scraped-state (v4.0.4).

The legacy sync engine rewrote state/scraped_articles.json per article via
core.StateTracker. The async KB engine uses the ticket engine's ScrapedState
(journal + batched compaction) with keys "{space_key}|{slug}" in a NEW v2
file. One-time migration seeds v2 from the legacy dict so nothing re-scrapes;
the legacy file is never modified (the RN/sync paths still own it).
"""
from __future__ import annotations
import json
from pathlib import Path

from scraper.scrape_state import ScrapedState


def _default_files():
    from scraper.kb_config import KB_ARTICLES_STATE_FILE
    from scraper.config import STATE_DIR
    return Path(STATE_DIR) / "scraped_articles_v2.json", Path(KB_ARTICLES_STATE_FILE)


def kb_key(space_key: str, slug: str) -> str:
    return f"{space_key}|{slug}"


def load_kb_state(state_file: Path | None = None, legacy_file: Path | None = None) -> ScrapedState:
    default_v2, default_legacy = _default_files()
    state_file = Path(state_file) if state_file else default_v2
    legacy_file = Path(legacy_file) if legacy_file else default_legacy
    st = ScrapedState(state_file=state_file)
    st.load()
    if not st.ids and legacy_file.exists():
        try:
            legacy = json.loads(legacy_file.read_text(encoding="utf-8"))
            for space_key, slugs in (legacy or {}).items():
                for slug in (slugs or {}):
                    st.mark(kb_key(space_key, slug))
            st.flush()
        except Exception:
            pass    # corrupt legacy: start empty; legacy file is left as-is
    return st
