# tests/test_log_pane.py
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])
from scraper.log_pane import LogPane


def test_emit_buffers_then_flush_renders_lines_and_blocks():
    """50 emit_log calls → blockCount unchanged; flush() → 50 lines,
    blockCount == 50 (per-line blocks so max_lines caps LINES)."""
    pane = LogPane()
    start_blocks = pane.blockCount()

    for i in range(50):
        pane.emit_log("info", f"line {i}")

    assert pane.blockCount() == start_blocks
    assert len(pane._buf) == 50

    pane.flush()

    assert pane._buf == []
    assert pane.blockCount() == 50
    text = pane.toPlainText()
    assert len(text.split("\n")) == 50
    assert "line 0" in text and "line 49" in text


def test_flush_escapes_html():
    """emit_log('info', '<script>x</script>') + flush → literal text in
    toPlainText, no raw tag in document HTML."""
    pane = LogPane()
    pane.emit_log("info", "<script>x</script>")
    pane.flush()

    assert "<script>x</script>" in pane.toPlainText()
    assert "<script>" not in pane.document().toHtml()


def test_max_lines_cap_trims_oldest():
    """max_lines=5, 8 lines flushed → 5 blocks remain, newest content present."""
    pane = LogPane(max_lines=5)
    for i in range(8):
        pane.emit_log("info", f"line {i}")
    pane.flush()

    assert pane.blockCount() == 5
    text = pane.toPlainText()
    assert "line 7" in text
    assert "line 0" not in text
