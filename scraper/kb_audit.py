"""Completeness audit for the KB library (v4.0.4, R3).

Compares live discovery against the JSON files actually on disk, per space.
Pure and injectable: discovery failures never raise — they mark the space with
the exception TYPE (org policy: no messages in reports/logs).
"""
from __future__ import annotations
from pathlib import Path


def audit_spaces(space_cfgs: list[dict], output_base: Path, discover=None) -> dict:
    if discover is None:
        from scraper.kb_discovery import discover_articles as discover
    output_base = Path(output_base)
    spaces: dict = {}
    totals = {"discovered": 0, "on_disk": 0, "missing": 0, "spaces_with_errors": 0}
    for cfg in space_cfgs:
        key = cfg["space_key"]
        entry = {"display_name": cfg["display_name"], "discovered": 0,
                 "on_disk": 0, "missing": [], "error": None}
        try:
            articles = discover(key)
        except Exception as exc:
            entry["error"] = type(exc).__name__
            totals["spaces_with_errors"] += 1
            spaces[key] = entry
            continue
        art_dir = output_base / cfg["product"] / cfg["lib_folder"]
        entry["discovered"] = len(articles)
        for art in articles:
            if (art_dir / f"{art['slug']}.json").exists():
                entry["on_disk"] += 1
            else:
                entry["missing"].append({**art, "space_key": key})
        totals["discovered"] += entry["discovered"]
        totals["on_disk"] += entry["on_disk"]
        totals["missing"] += len(entry["missing"])
        spaces[key] = entry
    return {"spaces": spaces, "totals": totals}
