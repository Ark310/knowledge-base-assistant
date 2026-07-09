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


def test_no_external_web_assets():
    # Offline posture: no http(s) CDN references in the bundled UI.
    for f in ("index.html", "app.js", "styles.css"):
        text = (webui_dir() / f).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, f
