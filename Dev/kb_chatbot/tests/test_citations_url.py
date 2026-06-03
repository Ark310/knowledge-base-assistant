import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.citations import validate, Citation
from Dev.kb_chatbot.chunker import Chunk


def _make_chunk(title, url, product="tradedesk", category="dealing"):
    return Chunk(
        id="test-1",
        text="Some content",
        metadata={"product": product, "category": category, "title": title, "url": url},
    )


def test_citation_has_url_field():
    c = Citation(raw="[Title](http://example.com)", title="Title", url="http://example.com")
    assert c.url == "http://example.com"


def test_validate_populates_url_on_verified_citation():
    chunk = _make_chunk("Book a Retail Deal", "https://help.contoso.example/display/DEAL")
    answer = "Do this step. [Book a Retail Deal](https://help.contoso.example/display/DEAL)"
    result = validate(answer, [chunk])
    assert len(result.verified) == 1
    assert result.verified[0].url == "https://help.contoso.example/display/DEAL"


def test_validate_marks_unknown_url_as_unverified():
    chunk = _make_chunk("Book a Retail Deal", "https://help.contoso.example/display/DEAL")
    answer = "See this. [Made Up Article](https://help.contoso.example/display/FAKE)"
    result = validate(answer, [chunk])
    assert len(result.unverified) == 1
    assert "[unverified]" in result.stripped_text


def test_validate_verified_citation_not_replaced():
    chunk = _make_chunk("Book a Retail Deal", "https://help.contoso.example/display/DEAL")
    answer = "Do this. [Book a Retail Deal](https://help.contoso.example/display/DEAL)"
    result = validate(answer, [chunk])
    assert "[unverified]" not in result.stripped_text
    assert "Book a Retail Deal" in result.stripped_text


def test_citation_url_with_parentheses_parses_fully():
    url = "https://help.contoso.example/display/TD/Booking+(Retail)"
    chunk = _make_chunk("Booking a Retail Deal", url)
    answer = f"Do this. [Booking a Retail Deal]({url})"
    result = validate(answer, [chunk])
    assert len(result.verified) == 1
    assert result.verified[0].url == url
