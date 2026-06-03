import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import tempfile
from Dev.kb_chatbot.settings import Settings, load_settings, save_settings
from Dev.kb_chatbot import config


def test_defaults_when_no_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        s = load_settings(path)
        assert s.library_path == config.LIBRARY_DEFAULT
        assert s.default_model == config.DEFAULT_MODEL
        assert s.confidence_floor == config.CONFIDENCE_FLOOR


def test_round_trip_save_and_load():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        original = Settings(
            library_path=Path("X:/some/library/kb"),
            default_model="claude-sonnet-4-6",
            confidence_floor=0.45,
        )
        save_settings(original, path)
        loaded = load_settings(path)
        assert loaded.library_path == Path("X:/some/library/kb")
        assert loaded.default_model == "claude-sonnet-4-6"
        assert loaded.confidence_floor == 0.45


def test_partial_file_falls_back_to_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        path.write_text(json.dumps({"default_model": "claude-sonnet-4-6"}), encoding="utf-8")
        loaded = load_settings(path)
        assert loaded.default_model == "claude-sonnet-4-6"
        assert loaded.library_path == config.LIBRARY_DEFAULT
        assert loaded.confidence_floor == config.CONFIDENCE_FLOOR
