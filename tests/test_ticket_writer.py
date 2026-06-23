import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.writers.ticket_writer import save_ticket

def _data():
    return {
        "ticket_id": "76511", "title": "Org config", "product": "TD Client Server",
        "status": "18 - Internal CSQA UAT", "organization": "Northwind Trading",
        "url": "https://portal.contoso.example/tickets/76511/edit", "scraped_at": "2026-06-23T00:00:00",
        "comments": [
            {"id": "1", "author": "Jordan Lee", "date": "Jun 22, 2026 at 12:57 PM",
             "internal": True, "body": "Done.", "attachments": []},
            {"id": "2", "author": "Alex Kim", "date": "Jun 18, 2026 at 9:10 AM",
             "internal": False, "body": "See log.",
             "attachments": [{"label": "error-log.txt", "saved_path": "attachments/76511/error-log.txt"}]},
        ],
        "resolution": {"text": "Fixed via script.",
                       "attachments": [{"label": "resolution-script.sql", "saved_path": "attachments/76511/resolution-script.sql"}]},
        "attachments": [
            {"filename": "error-log.txt", "saved_path": "attachments/76511/error-log.txt"},
            {"filename": "resolution-script.sql", "saved_path": "attachments/76511/resolution-script.sql"},
        ],
    }

def test_writes_json_and_md(tmp_path):
    save_ticket(_data(), tmp_path)
    assert (tmp_path / "ticket_76511.json").exists()
    assert (tmp_path / "ticket_76511.md").exists()

def test_json_roundtrips(tmp_path):
    save_ticket(_data(), tmp_path)
    loaded = json.loads((tmp_path / "ticket_76511.json").read_text(encoding="utf-8"))
    assert loaded["ticket_id"] == "76511"
    assert loaded["resolution"]["text"] == "Fixed via script."

def test_md_has_resolution_text_and_files(tmp_path):
    save_ticket(_data(), tmp_path)
    md = (tmp_path / "ticket_76511.md").read_text(encoding="utf-8")
    assert "## Resolution" in md and "Fixed via script." in md
    assert "resolution-script.sql" in md      # resolution file referenced
    assert "error-log.txt" in md              # comment file referenced
    assert "## Comments" in md

def test_md_handles_missing_resolution(tmp_path):
    d = _data(); d.pop("resolution")
    save_ticket(d, tmp_path)
    md = (tmp_path / "ticket_76511.md").read_text(encoding="utf-8")
    assert "## Resolution" not in md

def test_comment_images_decoded_to_files(tmp_path):
    # Inline base64 comment image must be decoded to a file; raw base64 must NOT remain in JSON.
    png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk"
               "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    d = {
        "ticket_id": "50001",
        "comments": [{
            "id": "2001", "author": "Jordan Lee", "date": "Jun 22, 2026 at 12:00 PM",
            "internal": False, "body": "See screenshot:", "attachments": [],
            "images": [{"mime": "image/png", "data": png_b64}],
        }],
    }
    save_ticket(d, tmp_path)
    loaded = json.loads((tmp_path / "ticket_50001.json").read_text(encoding="utf-8"))
    img = loaded["comments"][0]["images"][0]
    assert "data" not in img, "raw base64 must be stripped from the JSON"
    assert img["saved_path"] and Path(img["saved_path"]).exists()
    md = (tmp_path / "ticket_50001.md").read_text(encoding="utf-8")
    assert "![image]" in md
