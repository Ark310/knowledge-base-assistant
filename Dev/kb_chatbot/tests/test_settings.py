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


def test_default_model_is_sonnet():
    from Dev.kb_chatbot import config
    assert config.DEFAULT_MODEL == "claude-sonnet-4-6"


def test_settings_has_model_explicitly_set_field():
    from Dev.kb_chatbot.settings import Settings
    assert "model_explicitly_set" in Settings.__dataclass_fields__


def test_migrate_upgrades_implicit_haiku():
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, migrate_default_model
    s = Settings(library_path=config.LIBRARY_DEFAULT,
                 default_model="claude-haiku-4-5-20251001",
                 confidence_floor=config.CONFIDENCE_FLOOR,
                 model_explicitly_set=False)
    assert migrate_default_model(s) is True
    assert s.default_model == "claude-sonnet-4-6"


def test_migrate_keeps_explicit_haiku():
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, migrate_default_model
    s = Settings(library_path=config.LIBRARY_DEFAULT,
                 default_model="claude-haiku-4-5-20251001",
                 confidence_floor=config.CONFIDENCE_FLOOR,
                 model_explicitly_set=True)
    assert migrate_default_model(s) is False
    assert s.default_model == "claude-haiku-4-5-20251001"


def test_migrate_noop_for_sonnet():
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, migrate_default_model
    s = Settings(library_path=config.LIBRARY_DEFAULT,
                 default_model="claude-sonnet-4-6",
                 confidence_floor=config.CONFIDENCE_FLOOR,
                 model_explicitly_set=False)
    assert migrate_default_model(s) is False


def test_model_explicitly_set_round_trips():
    import tempfile
    from pathlib import Path
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, save_settings, load_settings
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "settings.json"
        s = Settings(library_path=config.LIBRARY_DEFAULT,
                     default_model="claude-haiku-4-5-20251001",
                     confidence_floor=config.CONFIDENCE_FLOOR,
                     model_explicitly_set=True)
        save_settings(s, p)
        assert load_settings(p).model_explicitly_set is True


def test_settings_has_default_provider_field():
    from Dev.kb_chatbot.settings import Settings
    assert "default_provider" in Settings.__dataclass_fields__


def test_default_provider_defaults_to_claude_when_absent():
    import tempfile
    from pathlib import Path
    from Dev.kb_chatbot.settings import load_settings
    with tempfile.TemporaryDirectory() as d:
        loaded = load_settings(Path(d) / "missing.json")
        assert loaded.default_provider == "claude"


def test_default_provider_round_trips():
    import tempfile
    from pathlib import Path
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, save_settings, load_settings
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "settings.json"
        s = Settings(library_path=config.LIBRARY_DEFAULT, default_model="gpt-5.4",
                     confidence_floor=config.CONFIDENCE_FLOOR,
                     default_provider="openai", model_explicitly_set=True)
        save_settings(s, p)
        loaded = load_settings(p)
        assert loaded.default_provider == "openai"
        assert loaded.default_model == "gpt-5.4"


def test_validation_resets_mismatched_model(tmp_path):
    import json
    from pathlib import Path
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import load_settings
    p = Path(tmp_path) / "settings.json"
    p.write_text(json.dumps({
        "library_path": str(config.LIBRARY_DEFAULT),
        "default_provider": "openai",
        "default_model": "claude-sonnet-4-6",
        "confidence_floor": config.CONFIDENCE_FLOOR,
        "model_explicitly_set": True,
    }), encoding="utf-8")
    loaded = load_settings(p)
    assert loaded.default_provider == "openai"
    assert loaded.default_model == "gpt-5.4"  # reset to openai's default
