import hashlib
import json
import tempfile
from pathlib import Path

from Dev.kb_chatbot.settings import check_learn_password, Settings, load_settings, save_settings


_CORRECT = "YOUR_LEARN_PASSWORD_HERE"
_CORRECT_HASH = hashlib.sha256(_CORRECT.encode()).hexdigest()


def test_check_learn_password_correct():
    assert check_learn_password(_CORRECT, _CORRECT_HASH) is True


def test_check_learn_password_wrong():
    assert check_learn_password("wrongpassword", _CORRECT_HASH) is False


def test_check_learn_password_empty():
    assert check_learn_password("", _CORRECT_HASH) is False


def test_settings_has_learn_mode_hash_field():
    assert "learn_mode_hash" in Settings.__dataclass_fields__


def test_settings_saves_and_loads_learn_mode_hash():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "settings.json"
        from Dev.kb_chatbot import config
        s = Settings(
            library_path=config.LIBRARY_DEFAULT,
            default_model=config.DEFAULT_MODEL,
            confidence_floor=config.CONFIDENCE_FLOOR,
            learn_mode_hash=_CORRECT_HASH,
        )
        save_settings(s, path)
        loaded = load_settings(path)
        assert loaded.learn_mode_hash == _CORRECT_HASH


def test_default_settings_have_default_hash():
    from Dev.kb_chatbot.settings import DEFAULT_LEARN_MODE_HASH
    with tempfile.TemporaryDirectory() as d:
        loaded = load_settings(Path(d) / "missing.json")
        assert loaded.learn_mode_hash == DEFAULT_LEARN_MODE_HASH


# ── Task 9: learn_writer tests ────────────────────────────────────────────────

from Dev.kb_chatbot.chat.learn_writer import write_learned_entry


def test_write_creates_json_file():
    with tempfile.TemporaryDirectory() as d:
        library_path = Path(d)
        write_learned_entry(
            library_path=library_path,
            product="tradedesk",
            topic="dealing",
            title="How to reverse a posted deal",
            body_md="To reverse: navigate to...",
            url="https://help.contoso.example/display/DEAL",
            original_question="How do I undo a posted deal?",
        )
        learned_dir = library_path / "learned"
        files = list(learned_dir.rglob("learned_*.json"))
        assert len(files) == 1
        # Topic becomes the category directory so ingest derives it from the path
        assert files[0].parent.name == "dealing"


def test_write_json_has_correct_schema():
    with tempfile.TemporaryDirectory() as d:
        library_path = Path(d)
        write_learned_entry(
            library_path=library_path,
            product="api",
            topic="functions",
            title="Using the REST API",
            body_md="Call GET /endpoint...",
            url="",
            original_question="How does the API work?",
        )
        files = list((library_path / "learned").rglob("*.json"))
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["space_key"] == "learned"
        assert data["space_name"] == "Learned"
        assert data["product"] == "api"
        assert data["title"] == "Using the REST API"
        assert data["body_md"] == "Call GET /endpoint..."
        assert "learned_at" in data
        assert data["contributed_by"] == "learn_mode"
        assert data["original_question"] == "How does the API work?"


def test_write_stable_filename_for_same_entry():
    with tempfile.TemporaryDirectory() as d:
        library_path = Path(d)
        kwargs = dict(library_path=library_path, product="tradedesk", topic="dealing",
                      title="Same Title", body_md="content", url="", original_question="q")
        write_learned_entry(**kwargs)
        write_learned_entry(**kwargs)
        files = list((library_path / "learned").rglob("*.json"))
        assert len(files) == 1  # second write overwrites (same stable hash)


def test_learned_entry_ingestable():
    """A learned entry must be picked up by the existing ingest pipeline."""
    from Dev.kb_chatbot.ingest import _gather_article_jsons
    with tempfile.TemporaryDirectory() as d:
        library_path = Path(d)
        write_learned_entry(
            library_path=library_path, product="tradedesk", topic="dealing",
            title="T", body_md="some body", url="", original_question="q",
        )
        found = _gather_article_jsons(library_path)
        assert len(found) == 1


def test_learned_entry_chunks_correctly():
    """A learned entry must produce valid chunks through build_article_chunks."""
    from Dev.kb_chatbot.chunker import build_article_chunks
    import json as _json
    with tempfile.TemporaryDirectory() as d:
        library_path = Path(d)
        out_path = write_learned_entry(
            library_path=library_path,
            product="tradedesk",
            topic="dealing",
            title="How to reverse a posted deal",
            body_md="To reverse a posted deal, navigate to Deal Entry and select Reverse.",
            url="https://help.contoso.example/display/DEAL",
            original_question="How do I undo a posted deal?",
        )
        data = _json.loads(out_path.read_text(encoding="utf-8"))
        chunks = build_article_chunks(data, out_path, library_path)
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert chunk.metadata["product"] == "tradedesk"
        assert "url" in chunk.metadata
        assert chunk.metadata["space_key"] == "learned"
        # Category derived from the topic directory in the path
        assert chunk.metadata["category"] == "dealing"


def test_topic_slugified_for_directory():
    """Messy topic labels become safe directory names."""
    with tempfile.TemporaryDirectory() as d:
        library_path = Path(d)
        out_path = write_learned_entry(
            library_path=library_path, product="tradedesk", topic="Deal Entry / Reversals!",
            title="T", body_md="b", url="", original_question="q",
        )
        assert out_path.parent.name == "deal_entry_reversals"


# ── Task 14: GUI wiring regression tests ─────────────────────────────────────

def test_settings_dialog_preserves_learn_mode_hash():
    """SettingsDialog.values() must carry learn_mode_hash through (regression)."""
    import inspect
    from Dev.kb_chatbot import gui
    src = inspect.getsource(gui.SettingsDialog.values)
    assert "learn_mode_hash" in src
