"""Persisted settings (JSON). V2.2 has no API key — Claude Code subprocess uses its own OAuth."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from Dev.kb_chatbot import config


@dataclass
class Settings:
    library_path: Path
    default_model: str
    confidence_floor: float


def load_settings(path: Path = config.SETTINGS_FILE) -> Settings:
    defaults = Settings(
        library_path=config.LIBRARY_DEFAULT,
        default_model=config.DEFAULT_MODEL,
        confidence_floor=config.CONFIDENCE_FLOOR,
    )
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    return Settings(
        library_path=Path(data.get("library_path", str(defaults.library_path))),
        default_model=data.get("default_model", defaults.default_model),
        confidence_floor=float(data.get("confidence_floor", defaults.confidence_floor)),
    )


def save_settings(settings: Settings, path: Path = config.SETTINGS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**asdict(settings), "library_path": str(settings.library_path)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
