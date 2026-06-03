import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chunker import build_article_chunks, _category_from_path, _split_body_md

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def _load(rel: str) -> tuple[dict, Path]:
    path = FIX / rel
    return json.loads(path.read_text(encoding="utf-8")), path


def test_chunk_for_short_article_yields_one_chunk():
    data, path = _load("web4/booking_deals/quick_pay.json")
    chunks = build_article_chunks(data, path, FIX)
    assert len(chunks) == 1
    assert "Quick Pay" in chunks[0].text


def test_chunk_metadata_includes_required_fields():
    data, path = _load("tradedesk/dealing/booking_spot_deal.json")
    chunks = build_article_chunks(data, path, FIX)
    md = chunks[0].metadata
    assert md["kind"] == "article"
    assert md["product"] == "tradedesk"
    assert md["category"] == "dealing"
    assert md["title"] == "Booking a Spot Deal"
    assert md["url"] == "http://example/tradedesk/booking-spot-deal"
    assert md["space_key"] == "TD"
    assert md["chunk_index"] == 0


def test_chunk_text_starts_with_breadcrumb():
    data, path = _load("tradedesk/dealing/booking_spot_deal.json")
    chunks = build_article_chunks(data, path, FIX)
    assert chunks[0].text.startswith("TradeDesk · dealing · Booking a Spot Deal")


def test_category_derived_from_path():
    p = FIX / "tradedesk" / "dealing" / "booking_spot_deal.json"
    assert _category_from_path(p, FIX) == "dealing"


def test_category_is_empty_when_no_subdir():
    p = FIX / "tradedesk" / "booking_spot_deal.json"
    assert _category_from_path(p, FIX) == ""


def test_long_article_is_split():
    body = "## Section A\n\n" + ("para para para. " * 200) + "\n\n## Section B\n\n" + ("text " * 200)
    parts = _split_body_md(body, target_words=100)
    assert len(parts) >= 2


def test_split_keeps_code_blocks_intact():
    body = "## intro\n\n```python\nfor i in range(10):\n    print(i)\n```\n\nafter code"
    parts = _split_body_md(body, target_words=500)
    joined = "\n".join(parts)
    assert "```python" in joined
    assert "for i in range(10):" in joined


def test_chunk_id_is_stable_across_runs():
    data, path = _load("saleshub/form_management/build_form.json")
    c1 = build_article_chunks(data, path, FIX)
    c2 = build_article_chunks(data, path, FIX)
    assert c1[0].id == c2[0].id


def test_chunks_for_all_six_products_built():
    paths = [
        "api/release_notes/api_release_25.json",
        "tradedesk/dealing/booking_spot_deal.json",
        "saleshub/form_management/build_form.json",
        "web2/payments/recurring_payment.json",
        "web4/booking_deals/quick_pay.json",
        "other/form_builder_docs/quick_start.json",
    ]
    products = set()
    for rel in paths:
        data, path = _load(rel)
        chunks = build_article_chunks(data, path, FIX)
        assert chunks
        products.add(chunks[0].metadata["product"])
    assert products == {"api", "tradedesk", "saleshub", "web2", "web4", "other"}
