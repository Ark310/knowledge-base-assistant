import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config


def test_state_dir_is_off_onedrive():
    assert "onedrive" not in str(config.STATE_DIR).lower()


def test_state_children_under_state_dir():
    for p in (config.CHROMA_DIR, config.CHATS_DIR, config.USAGE_FILE,
              config.SETTINGS_FILE, config.ANSWER_CACHE_FILE):
        assert str(p).startswith(str(config.STATE_DIR))


def test_migrate_copies_once(tmp_path, monkeypatch):
    old = tmp_path / "old_state"
    (old / "chroma").mkdir(parents=True)
    (old / "chroma" / "x.txt").write_text("hi", encoding="utf-8")
    new = tmp_path / "new_state"
    monkeypatch.setattr(config, "STATE_DIR", new)
    assert config.migrate_state_if_needed(old) is True
    assert (new / "chroma" / "x.txt").read_text(encoding="utf-8") == "hi"
    # second call is a no-op (new already populated)
    assert config.migrate_state_if_needed(old) is False
