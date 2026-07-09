import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.bridge import webui_dir


def test_webui_files_exist():
    d = webui_dir()
    for f in ("index.html", "app.js", "styles.css"):
        assert (d / f).exists(), f


def test_index_references_channel_and_app():
    html = (webui_dir() / "index.html").read_text(encoding="utf-8")
    assert "qrc:///qtwebchannel/qwebchannel.js" in html
    assert 'src="app.js"' in html
    assert 'href="styles.css"' in html


def test_no_external_asset_loads():
    # Offline posture: no external CDN <script src>/<link href>/<img src> loads.
    # (https URLs may still appear as data/citation values in app.js — that's fine.)
    import re
    html = (webui_dir() / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'(?:src|href)\s*=\s*"https?:', html), "external asset load in index.html"


def test_vendor_libs_present_and_referenced():
    d = webui_dir()
    assert (d / "vendor" / "marked.min.js").exists()
    assert (d / "vendor" / "purify.min.js").exists()
    html = (d / "index.html").read_text(encoding="utf-8")
    assert "vendor/marked.min.js" in html and "vendor/purify.min.js" in html
