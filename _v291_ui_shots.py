"""v2.9.1 UI screenshot harness — renders the themed surfaces OFFSCREEN and
grabs PNGs for the user's visual sign-off, WITHOUT touching the heavy InitWorker
(no model loading, no Chroma, no LLM). Build only the individual widgets / feed a
QTextBrowser sample bubble HTML / construct AboutDialog directly.

Run:  set QT_QPA_PLATFORM=offscreen & scraper\\venv\\Scripts\\python.exe _v291_ui_shots.py
Output: .wolf/designqc-captures/ui_header.png, ui_chat.png, ui_welcome.png, ui_about.png
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QTextBrowser
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtCore import Qt

from Dev.kb_chatbot import gui, config

OUT_DIR = ROOT / ".wolf" / "designqc-captures"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _save(widget, name: str) -> Path:
    path = OUT_DIR / name
    pm = widget.grab()
    ok = pm.save(str(path), "PNG")
    if not ok:
        raise RuntimeError(f"failed to save {path}")
    return path


def shoot_header() -> Path:
    """Standalone header bar (logo + title + version + brand underline)."""
    header = QFrame()
    header.setObjectName("HeaderBar")
    header.setStyleSheet(
        f"#HeaderBar {{ background:{gui.PALETTE['surface']}; "
        f"border-bottom:2px solid {gui.PALETTE['primary']}; }}")
    header.setFixedWidth(900)
    row = QHBoxLayout(header)
    row.setContentsMargins(12, 10, 12, 10)
    row.setSpacing(10)
    logo = QLabel()
    lp = gui._asset_path("contoso_logo.png")
    if lp:
        pm = QPixmap(lp)
        if not pm.isNull():
            logo.setPixmap(pm.scaledToHeight(28, Qt.SmoothTransformation))
    row.addWidget(logo)
    title = QLabel("KB Assistant")
    title.setStyleSheet(f"font-size:13pt; font-weight:600; color:{gui.PALETTE['text']};")
    row.addWidget(title)
    row.addStretch()
    ver = QLabel(f"v{config.APP_VERSION}")
    ver.setStyleSheet(f"color:{gui.PALETTE['muted']}; font-size:9.5pt;")
    row.addWidget(ver)
    header.adjustSize()
    return _save(header, "ui_header.png")


def shoot_chat() -> Path:
    """A QTextBrowser with sample YOU / AI / SYSTEM / ABSTAIN bubbles incl. a
    citation link — built via the real _build_message_html (escape-then-linkify)."""
    view = QTextBrowser()
    view.setFont(QFont("Segoe UI", 10))
    view.setOpenExternalLinks(True)
    view.setFixedSize(900, 560)
    blocks = [
        gui._build_message_html("user", "How do I reverse a posted deal in Treasury?",
                                "#000", "YOU:", "09:14:02"),
        gui._build_message_html(
            "ai",
            "To reverse a posted deal, open the deal, choose Actions → Reverse, "
            "then confirm. See [Reversing a posted deal]"
            "(https://help.contoso.example/display/TR/reverse) for the full steps.",
            "#000", "AI:", "09:14:09"),
        gui._build_message_html("user", "And for a settled one?", "#000", "YOU:", "09:15:20"),
        gui._build_message_html(
            "ai",
            "I'm not certain a settled deal can be reversed directly — it may need a "
            "compensating entry. Could you confirm the product and settlement status?",
            "#000", "CLARIFY:", "09:15:27"),
        gui._build_message_html("system", "Ready. Type a question below.",
                                "#000", "SYSTEM:", "09:13:55"),
    ]
    view.setHtml("".join(blocks))
    return _save(view, "ui_chat.png")


def shoot_welcome() -> Path:
    """The welcome / empty state (large centered logo + hint)."""
    view = QTextBrowser()
    view.setFont(QFont("Segoe UI", 10))
    view.setFixedSize(900, 560)
    view.setHtml(gui._welcome_html())
    return _save(view, "ui_welcome.png")


def shoot_about() -> Path:
    """The About dialog, constructed directly (no MainWindow / no InitWorker)."""
    dlg = gui.AboutDialog(None, status_text="Provider: Claude · Sonnet — "
                          "local retrieval over the Contoso knowledge base.")
    dlg.adjustSize()
    return _save(dlg, "ui_about.png")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(gui._app_stylesheet())
    produced = [shoot_header(), shoot_chat(), shoot_welcome(), shoot_about()]
    for p in produced:
        size = p.stat().st_size if p.exists() else 0
        print(f"wrote {p}  ({size} bytes)")
    missing = [p for p in produced if not p.exists() or p.stat().st_size == 0]
    if missing:
        print("MISSING/EMPTY:", missing)
        return 1
    print(f"OK — {len(produced)} PNGs written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
