"""kb_state — journaled KB scraped-state + one-time legacy migration."""
import json

from scraper.kb_state import kb_key, load_kb_state


def test_kb_key_format():
    assert kb_key("SA", "some_article") == "SA|some_article"


def test_fresh_state_no_legacy(tmp_path):
    st = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=tmp_path / "legacy.json")
    assert st.ids == set()
    st.mark(kb_key("SA", "a")); st.flush()
    assert set(json.loads((tmp_path / "v2.json").read_text())) == {"SA|a"}


def test_migrates_legacy_once_and_leaves_legacy_untouched(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({
        "SA": {"a1": {"url": "u", "scraped_at": "t"}, "a2": {"url": "u", "scraped_at": "t"}},
        "howto": {"b1": {"url": "u", "scraped_at": "t"}},
    }))
    before = legacy.read_text()
    st = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=legacy)
    assert st.ids == {"SA|a1", "SA|a2", "howto|b1"}
    assert legacy.read_text() == before                      # read-only migration
    # migrated ids are persisted (survive a reload without legacy re-read)
    st2 = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=tmp_path / "gone.json")
    assert st2.ids == {"SA|a1", "SA|a2", "howto|b1"}


def test_existing_v2_state_skips_migration(tmp_path):
    (tmp_path / "v2.json").write_text(json.dumps(["SA|kept"]))
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"SA": {"ignored": {"url": "u", "scraped_at": "t"}}}))
    st = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=legacy)
    assert st.ids == {"SA|kept"}                             # no merge once v2 exists


def test_corrupt_legacy_degrades_to_empty(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text("{not json")
    st = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=legacy)
    assert st.ids == set()
