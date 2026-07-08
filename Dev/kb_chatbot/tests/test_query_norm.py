import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.query_norm import normalize, tokenize


def test_normalize_lowercases_and_collapses_whitespace():
    assert normalize("  How   DO  I  ") == "how do i"

def test_normalize_strips_punctuation_but_keeps_hash():
    assert normalize("ticket #75919: null?") == "ticket #75919 null"

def test_normalize_folds_product_synonyms_to_slug():
    assert normalize("FormFlow setup") == "formflow setup"
    assert normalize("formflow setup") == "formflow setup"
    assert normalize("SalesHub report") == "saleshub report"
    assert normalize("TD dealing") == "tradedesk dealing"

def test_normalize_is_idempotent():
    q = "How do I configure FormFlow in TD?"
    assert normalize(normalize(q)) == normalize(q)

def test_normalize_empty():
    assert normalize("") == ""

def test_tokenize_splits_lowercases_keeps_digits_and_hash():
    assert tokenize("GetWebDeal #75919 NULL") == ["getwebdeal", "#75919", "null"]

def test_tokenize_empty():
    assert tokenize("") == []
