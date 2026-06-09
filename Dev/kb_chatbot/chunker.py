"""V2.2 chunker: build searchable chunks from flat-article JSON files."""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from Dev.kb_chatbot import config


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _category_from_path(article_path: Path, library_root: Path) -> str:
    """Derive a category slug from the article path:
       library_root/<product>/<category>/.../<file>.json  → category."""
    try:
        rel = article_path.relative_to(library_root).parts
    except ValueError:
        return ""
    if len(rel) >= 3:
        return rel[1]
    return ""


def _stable_id(space_key: str, title: str, chunk_index: int) -> str:
    base = f"{space_key}|{title}|{chunk_index}"
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"art_{h}"


def _split_body_md(body_md: str, target_words: int = config.CHUNK_TARGET_WORDS,
                   overlap_words: int = config.CHUNK_OVERLAP_WORDS) -> list[str]:
    """Split markdown text into chunks targeting `target_words` words.
       Splits on '## '/'### ' headings, sub-splits long sections on paragraph breaks,
       never splits inside fenced code blocks."""
    if not body_md.strip():
        return []

    code_blocks: list[str] = []
    def _stash(match: re.Match) -> str:
        code_blocks.append(match.group(0))
        return f" CODE{len(code_blocks)-1} "
    masked = re.sub(r"```.*?```", _stash, body_md, flags=re.DOTALL)

    sections = re.split(r"(?m)^(?=#{1,3} )", masked)
    sections = [s.strip("\n") for s in sections if s.strip()]

    def _unmask(text: str) -> str:
        def _restore(match: re.Match) -> str:
            return code_blocks[int(match.group(1))]
        return re.sub(r" CODE(\d+) ", _restore, text)

    chunks: list[str] = []
    for section in sections:
        heading_line = ""
        body = section
        m = re.match(r"^(#{1,3} [^\n]+)\n?(.*)$", section, flags=re.DOTALL)
        if m:
            heading_line = m.group(1)
            body = m.group(2).strip("\n")

        words = body.split()
        if len(words) <= target_words:
            chunks.append(_unmask(section))
            continue

        paragraphs = re.split(r"\n\s*\n", body)
        buf: list[str] = []
        buf_words = 0
        for para in paragraphs:
            p_words = len(para.split())
            if buf and buf_words + p_words > target_words:
                chunks.append(_unmask((heading_line + "\n\n" if heading_line else "") + "\n\n".join(buf)))
                buf = [para]
                buf_words = p_words
            else:
                buf.append(para)
                buf_words += p_words
        if buf:
            chunks.append(_unmask((heading_line + "\n\n" if heading_line else "") + "\n\n".join(buf)))

    if overlap_words > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:]):
            tail = " ".join(prev.split()[-overlap_words:])
            overlapped.append(f"[…] {tail}\n\n{cur}")
        chunks = overlapped

    return chunks


def _breadcrumb(product: str, category: str, title: str) -> str:
    display = config.PRODUCT_DISPLAY.get(product, product)
    return f"{display} · {category or 'general'} · {title}"


def build_article_chunks(article_data: dict, article_path: Path, library_root: Path,
                         target_words: int = config.CHUNK_TARGET_WORDS,
                         overlap_words: int = config.CHUNK_OVERLAP_WORDS) -> list[Chunk]:
    product = article_data.get("product", "unknown")
    title = article_data.get("title", "")
    space_key = article_data.get("space_key", "")
    space_name = article_data.get("space_name", "")
    url = article_data.get("url", "")
    body_md = article_data.get("body_md", "")
    category = _category_from_path(article_path, library_root)

    breadcrumb = _breadcrumb(product, category, title)
    parts = _split_body_md(body_md, target_words, overlap_words)
    if not parts:
        return []

    try:
        rel = article_path.with_suffix(".md").relative_to(library_root.parent)
        md_path = rel.as_posix()
    except ValueError:
        md_path = article_path.with_suffix(".md").as_posix()

    chunks: list[Chunk] = []
    for idx, part in enumerate(parts):
        text = f"{breadcrumb}\n\n{part}"
        chunks.append(Chunk(
            id=_stable_id(space_key or url or title, title, idx),
            text=text,
            metadata={
                "kind": "article",
                "product": product,
                "category": category,
                "title": title,
                "space_key": space_key,
                "space_name": space_name,
                "url": url,
                "chunk_index": idx,
                "md_path": md_path,
            },
        ))
    return chunks
