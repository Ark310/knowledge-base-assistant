import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import gui


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
