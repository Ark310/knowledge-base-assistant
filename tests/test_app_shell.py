# tests/test_app_shell.py
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

def test_mainwindow_has_settings_button_and_icon():
    from scraper.gui import MainWindow
    win = MainWindow()
    assert hasattr(win, "btn_settings")
    assert win.windowIcon() is not None and not win.windowIcon().isNull()

def test_app_stylesheet_applies():
    from scraper import theme
    _app.setStyleSheet(theme.app_stylesheet())
    assert theme.PALETTE["brand"] in _app.styleSheet()
