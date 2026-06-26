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


def test_settings_dialog_persists_browser_mode(tmp_path, monkeypatch):
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    dlg = SettingsDialog()
    dlg.set_browser_mode_value("multi")   # helper the dialog exposes for the control
    dlg._save()                            # the dialog's save handler
    assert s.browser_mode() == "multi"
