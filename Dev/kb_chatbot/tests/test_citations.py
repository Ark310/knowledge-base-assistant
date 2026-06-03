import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.citations import parse_citations, validate
from Dev.kb_chatbot.chunker import Chunk


def _chunk(product, category, title):
    return Chunk(id="x", text="...",
                 metadata={"product": product, "category": category,
                           "title": title, "kind": "article"})


def test_parses_well_formed_citation():
    txt = "Some claim [TradeDesk · dealing · Booking a Spot Deal]."
    cites = parse_citations(txt)
    assert len(cites) == 1
    c = cites[0]
    assert c.product == "TradeDesk"
    assert c.category == "dealing"
    assert c.title == "Booking a Spot Deal"


def test_parses_multiple_citations():
    txt = "A [TradeDesk · dealing · Booking a Spot Deal]. B [SalesHub · form_management · Building a Customer Onboarding Form]."
    cites = parse_citations(txt)
    assert len(cites) == 2


def test_ignores_malformed_citation_missing_separator():
    txt = "[TradeDesk dealing Booking a Spot Deal]"
    cites = parse_citations(txt)
    assert cites == []


def test_validator_accepts_matching_citation():
    retrieved = [_chunk("tradedesk", "dealing", "Booking a Spot Deal")]
    answer = "X [TradeDesk · dealing · Booking a Spot Deal]."
    result = validate(answer, retrieved)
    assert result.all_verified is True
    assert result.stripped_text == answer


def test_validator_strips_hallucinated_citation():
    retrieved = [_chunk("tradedesk", "dealing", "Booking a Spot Deal")]
    answer = "X [TradeDesk · invented · A Fake Article]."
    result = validate(answer, retrieved)
    assert result.all_verified is False
    assert "[unverified]" in result.stripped_text
    assert "A Fake Article" not in result.stripped_text


def test_validator_general_category_matches_empty_metadata():
    retrieved = [_chunk("saleshub", "", "Welcome")]
    answer = "Hi [SalesHub · general · Welcome]."
    result = validate(answer, retrieved)
    assert result.all_verified is True
