"""Domain synonym expansion for the BM25 query side only.
The vector query stays raw — embeddings already handle soft synonymy."""
from __future__ import annotations
import logging
import re
from pathlib import Path

import yaml

log = logging.getLogger("kb_chatbot.expansion")


def load_synonyms(path: Path) -> list[list[str]]:
    """Load synonym groups from YAML ({groups: [[a, b], ...]}).
    Malformed or missing files return [] with a warning — never raise."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("Synonyms file not found: %s — expansion disabled", path)
        return []
    except Exception as exc:
        log.warning("Failed to parse %s: %s — expansion disabled", path, exc)
        return []
    if not isinstance(data, dict):
        log.warning("Synonyms file %s is not a mapping — expansion disabled", path)
        return []
    groups = data.get("groups")
    if not isinstance(groups, list):
        log.warning("Synonyms file %s has no 'groups' list — expansion disabled", path)
        return []
    out: list[list[str]] = []
    for g in groups:
        if isinstance(g, list) and len(g) >= 2 and all(isinstance(t, str) and t.strip() for t in g):
            out.append([t.strip().lower() for t in g])
        else:
            log.warning("Skipping malformed synonym group: %r", g)
    return out


def expand_query(query: str, groups: list[list[str]]) -> str:
    """Append synonyms of any group term found (whole-word) in the query.
    Returns the original query followed by the unique additions."""
    lowered = query.lower()
    additions: list[str] = []
    for group in groups:
        matched = any(
            re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered)
            for term in group
        )
        if not matched:
            continue
        for term in group:
            present = re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered)
            if not present and term not in additions:
                additions.append(term)
    return query if not additions else f"{query} {' '.join(additions)}"
