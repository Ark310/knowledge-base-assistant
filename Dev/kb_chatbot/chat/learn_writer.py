"""Write user-contributed KB entries to library/learned/ for ingestion."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


def _slugify(text: str) -> str:
    """Lowercase, alphanumeric + underscores — safe as a directory name."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "general"


def write_learned_entry(
    *,
    library_path: Path,
    product: str,
    topic: str,
    title: str,
    body_md: str,
    url: str,
    original_question: str,
) -> Path:
    """Save a Learn Mode contribution as an article-schema JSON under
    <library>/learned/<topic-slug>/. Filename is a stable hash of
    (product, title) so re-saving the same correction overwrites rather
    than duplicates.

    The topic becomes the second path segment so the ingest pipeline's
    _category_from_path derives it as the chunk category
    (library/<learned>/<topic>/<file> → category = topic).
    """
    topic_dir = library_path / "learned" / _slugify(topic)
    topic_dir.mkdir(parents=True, exist_ok=True)

    stable_key = hashlib.sha1(f"{product}:{title}".encode()).hexdigest()[:16]
    filename = f"learned_{stable_key}.json"

    entry = {
        "space_key": "learned",
        "space_name": "Learned",
        "product": product,
        "category": topic,
        "title": title,
        "url": url,
        "body_md": body_md,
        "learned_at": datetime.now().isoformat(timespec="seconds"),
        "contributed_by": "learn_mode",
        "original_question": original_question,
    }

    out_path = topic_dir / filename
    out_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
