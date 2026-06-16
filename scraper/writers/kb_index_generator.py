from __future__ import annotations
import json
from pathlib import Path

_PRODUCT_ORDER = ["tradedesk", "web2", "web4", "api", "saleshub", "formflow", "other"]
_PRODUCT_LABELS = {
    "tradedesk":    "TradeDesk KB",
    "web2":        "Web 2.5 KB",
    "web4":        "Web 4.0 KB",
    "api":         "API KB",
    "saleshub":     "SalesHub KB",
    "formflow":  "FormFlow KB",
    "other":       "Other",
}


def generate_kb_index(kb_library_base: Path, spaces: list[dict]) -> None:
    """Build index.json and index.md from all .json article files in kb_library_base."""
    articles: list[dict] = []

    for json_file in sorted(kb_library_base.rglob("*.json")):
        if json_file.name == "index.json":
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            articles.append({
                "title":      data.get("title", ""),
                "space_key":  data.get("space_key", ""),
                "space_name": data.get("space_name", ""),
                "product":    data.get("product", ""),
                "url":        data.get("url", ""),
                "scraped_at": data.get("scraped_at", ""),
            })
        except Exception:
            continue

    (kb_library_base / "index.json").write_text(
        json.dumps({"total": len(articles), "articles": articles}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    by_product: dict[str, list[dict]] = {}
    for art in articles:
        by_product.setdefault(art["product"], []).append(art)

    lines = [f"# Contoso Knowledge Base Index\n\n**Total articles:** {len(articles)}\n"]
    for product in _PRODUCT_ORDER:
        if product not in by_product:
            continue
        label = _PRODUCT_LABELS.get(product, product)
        lines.append(f"\n## {label}\n")
        lines.append("| Title | Space | URL |")
        lines.append("|---|---|---|")
        for art in sorted(by_product[product], key=lambda a: (a["space_name"], a["title"])):
            title = art["title"].replace("|", "\\|")
            space = art["space_name"].replace("|", "\\|")
            lines.append(f"| {title} | {space} | {art['url']} |")

    (kb_library_base / "index.md").write_text("\n".join(lines), encoding="utf-8")
