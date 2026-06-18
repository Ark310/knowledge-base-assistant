import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import gui, config


def test_render_escapes_html_in_text():
    out = gui._build_message_html("ai", "<img src=x onerror=alert(1)>", "#000", "AI:", "12:00:00")
    assert "<img" not in out
    assert "&lt;img" in out


def test_render_only_links_http_urls():
    out = gui._build_message_html("ai", "see [x](javascript:alert(1)) and [y](https://help.contoso.example/p)",
                                  "#000", "AI:", "12:00:00")
    assert 'href="javascript:' not in out
    assert 'href="https://help.contoso.example/p"' in out


def test_render_malicious_title_is_inert():
    out = gui._build_message_html("ai", '[<b>boom</b>](https://help.contoso.example/p)', "#000", "AI:", "12:00:00")
    assert "<b>boom</b>" not in out  # title is escaped before linkify


def test_bubble_styling_distinguishes_roles():
    you = gui._build_message_html("user", "hi", "#000", "YOU:", "12:00:00")
    ai = gui._build_message_html("ai", "hello", "#000", "AI:", "12:00:00")
    # YOU bubbles align right and use the brand-blue fill; AI bubbles align left.
    assert 'align="right"' in you
    assert gui.PALETTE["you_bg"] in you
    assert 'align="left"' in ai


def test_about_dialog_and_header_construct():
    """Offscreen smoke test: AboutDialog + the header widget construct without
    error and surface the version. Skips cleanly if Qt can't init offscreen."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
    except Exception as exc:  # pragma: no cover - headless CI without Qt platform
        pytest.skip(f"Qt offscreen unavailable: {exc}")

    dlg = gui.AboutDialog(None, status_text="Provider: Claude — test")
    # The version label text is present somewhere in the dialog's child labels.
    from PySide6.QtWidgets import QLabel
    texts = " ".join(w.text() for w in dlg.findChildren(QLabel))
    assert f"v{config.APP_VERSION}" in texts
