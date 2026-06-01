from __future__ import annotations
import json
import re
from pathlib import Path


def safe_slug(text: str) -> str:
    """Convert article title to a filesystem-safe slug, max 120 chars."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:120] or "untitled"


def save_article(data: dict, kb_library_base: Path, space_cfg: dict) -> None:
    """Save article data as .json and .md files.

    Writes to:
      kb_library_base / space_cfg["product"] / space_cfg["lib_folder"] / {slug}.{json|md}
    """
    article_dir = kb_library_base / space_cfg["product"] / space_cfg["lib_folder"]
    article_dir.mkdir(parents=True, exist_ok=True)

    slug = safe_slug(data["title"])

    (article_dir / f"{slug}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    frontmatter = (
        "---\n"
        f"title: {data['title']}\n"
        f"space: {data['space_name']}\n"
        f"product: {data['product']}\n"
        f"url: {data['url']}\n"
        f"scraped_at: {data['scraped_at']}\n"
        "---\n\n"
    )
    (article_dir / f"{slug}.md").write_text(
        frontmatter + data["body_md"], encoding="utf-8"
    )
