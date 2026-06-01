from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

# Sections counted/listed as "features"
_FEATURE_SECTIONS = ["enhancements", "tasks"]


def _safe(version: str) -> str:
    return version.replace(" ", "_").replace("/", "-").strip()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_versions(library_base: Path, product: str) -> list[dict]:
    vdir = library_base / product / "versions"
    if not vdir.exists():
        return []
    out = []
    for f in vdir.glob("*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    # newest-first by version tuple when numeric, else string
    def key(v):
        parts = v.get("version", "").replace("-", ".").split(".")
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return (v.get("version", ""),)
    return sorted(out, key=key, reverse=True)


def _row_line(row: dict) -> str:
    ident = row.get("id")
    details = row.get("details") or next((v for v in row.values() if v), "")
    return f"- **{ident}** — {details}" if ident else f"- {details}"


def _generate_product(library_base: Path, product: str, display: str):
    versions = _load_versions(library_base, product)
    pdir = library_base / product
    pdir.mkdir(parents=True, exist_ok=True)

    # CHANGELOG
    lines = [f"# {display} — Changelog", "", f"*Generated: {_now()}*", "", "---", ""]
    for v in versions:
        parts = []
        for sec, label in [("enhancements", "enhancement"), ("tasks", "task"),
                           ("bugs", "bug fix"), ("schema_changes", "schema change")]:
            n = len(v.get(sec, []))
            if n:
                parts.append(f"{n} {label}(s)")
        summary = ", ".join(parts) if parts else "no items extracted"
        lines += [f"## {v['version']}", "", f"*{v['url']}*", "",
                  f"**Summary:** {summary}", "",
                  f"[Details](versions/{_safe(v['version'])}.md)", "", "---", ""]
    (pdir / "CHANGELOG.md").write_text("\n".join(lines), encoding="utf-8")

    # features-list (enhancements + tasks)
    lines = [f"# {display} — All Features & Enhancements", "", f"*Generated: {_now()}*", "", "---", ""]
    for v in versions:
        rows = [r for sec in _FEATURE_SECTIONS for r in v.get(sec, [])]
        if rows:
            lines += [f"## {v['version']}", ""]
            lines += [_row_line(r) for r in rows]
            lines.append("")
    (pdir / "features-list.md").write_text("\n".join(lines), encoding="utf-8")

    # bugs-list
    lines = [f"# {display} — All Bug Fixes", "", f"*Generated: {_now()}*", "", "---", ""]
    for v in versions:
        rows = v.get("bugs", [])
        if rows:
            lines += [f"## {v['version']}", ""]
            lines += [_row_line(r) for r in rows]
            lines.append("")
    (pdir / "bugs-list.md").write_text("\n".join(lines), encoding="utf-8")


def _generate_master(library_base: Path, products: dict):
    lines = ["# Contoso Knowledge Base — Release Notes Library", "",
             f"*Generated: {_now()}*", "", "---", ""]
    for key, cfg in products.items():
        versions = _load_versions(library_base, key)
        lines += [f"## {cfg['display_name']}", "",
                  f"**{len(versions)} version(s) scraped**", "",
                  f"- [Changelog]({key}/CHANGELOG.md)",
                  f"- [All Features]({key}/features-list.md)",
                  f"- [All Bugs]({key}/bugs-list.md)", ""]
        for v in versions[:10]:
            lines.append(f"- [{v['version']}]({key}/versions/{_safe(v['version'])}.md)")
        if len(versions) > 10:
            lines.append(f"- *...and {len(versions) - 10} more (see Changelog)*")
        lines += ["", "---", ""]
    library_base.mkdir(parents=True, exist_ok=True)
    (library_base / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")


def generate_all(library_base: Path, products: dict):
    for key, cfg in products.items():
        _generate_product(library_base, key, cfg["display_name"])
    _generate_master(library_base, products)
