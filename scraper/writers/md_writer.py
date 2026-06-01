from __future__ import annotations
from pathlib import Path

# Canonical section -> Markdown heading
_SECTION_TITLES = {
    "enhancements": "Enhancements and New Features",
    "bugs": "Bugs",
    "schema_changes": "Schema Changes",
    "tasks": "Tasks",
}
_SECTION_ORDER = ["enhancements", "tasks", "bugs", "schema_changes"]


def safe_name(version: str) -> str:
    return version.replace(" ", "_").replace("/", "-").strip()


def _columns_for(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for row in rows:
        for k in row:
            if k not in cols:
                cols.append(k)
    return cols


def _escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _render_section(name: str, rows: list[dict]) -> list[str]:
    cols = _columns_for(rows)
    lines = [f"## {_SECTION_TITLES.get(name, name.title())}", ""]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(_escape(row.get(c, "")) for c in cols) + " |")
    lines.append("")
    return lines


def render_md(data: dict) -> str:
    display = data["product"].replace("_", " ").title()
    lines = [
        f"# {display} — {data.get('title', 'Version ' + data['version'])}",
        "",
        f"**Version:** {data['version']}  ",
        f"**URL:** {data['url']}  ",
        f"**Scraped:** {data['scraped_at']}  ",
        f"**Screenshot:** `{data.get('screenshot', '')}`",
        "",
    ]
    for name in _SECTION_ORDER:
        rows = data.get(name)
        if rows:
            lines += _render_section(name, rows)
    return "\n".join(lines)


def save_version(data: dict, library_base: Path) -> Path:
    output_dir = library_base / data["product"] / "versions"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_name(data['version'])}.md"
    output_path.write_text(render_md(data), encoding="utf-8")
    return output_path
