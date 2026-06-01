from __future__ import annotations
import re
from pathlib import Path


def update_release_notes_urls(config_path: Path, resolved: dict[str, str]) -> None:
    """
    Robustly set each product's release_notes_url in config.py.
    For each product key, replaces the FIRST "release_notes_url": "..." that
    appears after that product key, anchored on the key so blocks don't bleed.
    """
    text = config_path.read_text(encoding="utf-8")
    for product_key, url in resolved.items():
        pattern = re.compile(
            r'("' + re.escape(product_key) + r'"\s*:\s*\{.*?"release_notes_url"\s*:\s*)"[^"]*"',
            re.DOTALL,
        )
        replacement = r'\1"' + url.replace("\\", "\\\\") + '"'
        text, n = pattern.subn(replacement, text, count=1)
        if n == 0:
            raise ValueError(f"Could not locate release_notes_url for product '{product_key}'")
    config_path.write_text(text, encoding="utf-8")
