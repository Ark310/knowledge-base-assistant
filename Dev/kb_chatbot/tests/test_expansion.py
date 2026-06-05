import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.expansion import load_synonyms, expand_query

GROUPS = [["deal", "trade"], ["post", "book"], ["fx rate", "exchange rate"]]


def test_expand_appends_synonyms_of_matched_terms():
    out = expand_query("how do I post a deal", GROUPS)
    assert "book" in out and "trade" in out
    assert out.startswith("how do I post a deal")


def test_expand_matches_whole_words_only():
    # 'posting' must not match the term 'post'... but 'deal' matches exactly
    out = expand_query("dealing with postage", GROUPS)
    assert out == "dealing with postage"


def test_expand_handles_multiword_terms():
    out = expand_query("what is the fx rate today", GROUPS)
    assert "exchange rate" in out


def test_expand_no_duplicates_when_synonym_already_present():
    out = expand_query("post or book a deal", GROUPS)
    assert out.split().count("book") == 1


def test_load_synonyms_reads_groups(tmp_path):
    f = tmp_path / "syn.yaml"
    f.write_text("groups:\n  - [deal, trade]\n  - [post, book]\n", encoding="utf-8")
    assert load_synonyms(f) == [["deal", "trade"], ["post", "book"]]


def test_load_synonyms_malformed_returns_empty(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("groups: {not: [a, list\n", encoding="utf-8")
    assert load_synonyms(f) == []


def test_load_synonyms_missing_file_returns_empty(tmp_path):
    assert load_synonyms(tmp_path / "absent.yaml") == []
