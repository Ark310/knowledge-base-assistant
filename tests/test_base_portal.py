import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.portal import base_portal as bp

def test_empty_ticket_has_canonical_shape():
    t = bp.empty_ticket("76511", "https://x/tickets/76511/edit")
    assert t["ticket_id"] == "76511"   # the key save_ticket writes by
    assert t["url"].endswith("/76511/edit")
    assert t["comments"] == [] and t["attachments"] == []
    assert t["resolution"] == {"text": "", "comments": [], "attachments": []}

def test_looks_like_login_only_when_no_ticket_fields():
    assert bp.looks_like_login("Please sign in") is True
    assert bp.looks_like_login("sign in <button class='floating-dropdown-btn'>") is False
    assert bp.looks_like_login("a fully rendered ticket") is False
