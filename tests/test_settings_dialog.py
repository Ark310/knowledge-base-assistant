# tests/test_settings_dialog.py
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
import scraper.app_settings as aps
from scraper.settings_dialog import SettingsDialog

_app = QApplication.instance() or QApplication([])

def test_dialog_constructs_and_prefills(tmp_path, monkeypatch):
    monkeypatch.setattr(aps, "tickets_dir", lambda: tmp_path / "tickets")
    monkeypatch.setattr(aps, "kb_dir", lambda: tmp_path / "kb")
    dlg = SettingsDialog()
    assert str(tmp_path / "tickets") in dlg.inp_tickets.text()
    assert str(tmp_path / "kb") in dlg.inp_kb.text()

def test_credentials_section_hidden_by_default():
    dlg = SettingsDialog()
    assert dlg.cred_box.isVisible() is False  # collapsed until expanded
