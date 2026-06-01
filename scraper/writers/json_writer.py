from __future__ import annotations
import json
from pathlib import Path


def safe_name(version: str) -> str:
    return version.replace(" ", "_").replace("/", "-").strip()


def save_version(data: dict, library_base: Path) -> Path:
    output_dir = library_base / data["product"] / "versions"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_name(data['version'])}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return output_path
