import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.citations import parse_citations, validate
from Dev.kb_chatbot.chunker import Chunk


def _chunk(product, category, title, url="http://example/article"):
    return Chunk(id="x", text="...",
                 metadata={"product": product, "category": category,
                           "title": title, "url": url, "kind": "article"})


def test_parses_well_formed_citation():
    txt = "Some claim [Booking a Spot Deal](https://help.contoso.example/display/TD/booking)."
    cites = parse_citations(txt)
    assert len(cites) == 1
    c = cites[0]
    assert c.title == "Booking a Spot Deal"
    assert c.url == "https://help.contoso.example/display/TD/booking"


def test_parses_multiple_citations():
    txt = (
        "A [Booking a Spot Deal](https://help.contoso.example/display/TD/booking). "
        "B [Building a Customer Onboarding Form](https://help.contoso.example/display/SH/form)."
    )
    cites = parse_citations(txt)
    assert len(cites) == 2


def test_ignores_malformed_citation_missing_url():
    txt = "[Booking a Spot Deal]"
    cites = parse_citations(txt)
    assert cites == []


def test_validator_accepts_matching_citation():
    url = "https://help.contoso.example/display/TD/booking"
    retrieved = [_chunk("tradedesk", "dealing", "Booking a Spot Deal", url=url)]
    answer = f"X [Booking a Spot Deal]({url})."
    result = validate(answer, retrieved)
    assert result.all_verified is True
    assert result.stripped_text == answer


def test_validator_strips_hallucinated_citation():
    url = "https://help.contoso.example/display/TD/booking"
    retrieved = [_chunk("tradedesk", "dealing", "Booking a Spot Deal", url=url)]
    answer = "X [A Fake Article](https://help.contoso.example/display/TD/fake)."
    result = validate(answer, retrieved)
    assert result.all_verified is False
    assert "[unverified]" in result.stripped_text
    assert "A Fake Article" not in result.stripped_text


def test_validator_url_match_ignores_title_mismatch():
    # URL match is the authority — same URL, different title still verifies
    url = "https://help.contoso.example/display/SH/welcome"
    retrieved = [_chunk("saleshub", "", "Welcome", url=url)]
    answer = f"Hi [Getting Started]({url})."  # citation title differs from chunk title "Welcome"
    result = validate(answer, retrieved)
    assert result.all_verified is True


def test_ticket_citation_validates_against_resolution_url():
    from Dev.kb_chatbot.citations import validate
    from Dev.kb_chatbot.chunker import Chunk
    url = "https://support.contoso.example/Resolution.aspx?bugid=75100"
    chunk = Chunk(id="ticket_x", text="…",
                  metadata={"kind": "ticket", "ticket_id": "75100",
                            "title": "Ticket #75100", "url": url, "product": "tradedesk"})
    answer = f"Restart the FixApp session. [Ticket #75100 · TradeDesk]({url})"
    res = validate(answer, [chunk])
    assert len(res.verified) == 1
    assert "[unverified]" not in res.stripped_text
