# tests/test_app_settings.py
import sys, json, importlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def _fresh(tmp_path, monkeypatch):
    import scraper.config as config
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=True)
    monkeypatch.setattr(config, "LIBRARY_BASE", tmp_path / "library", raising=True)
    import scraper.app_settings as aps
    importlib.reload(aps)
    return aps

def test_defaults_when_no_file(tmp_path, monkeypatch):
    aps = _fresh(tmp_path, monkeypatch)
    assert aps.tickets_dir() == tmp_path / "library" / "tickets"
    assert aps.kb_dir() == tmp_path / "library" / "kb"

def test_round_trip(tmp_path, monkeypatch):
    aps = _fresh(tmp_path, monkeypatch)
    aps.save(str(tmp_path / "T"), str(tmp_path / "K"))
    assert aps.tickets_dir() == tmp_path / "T"
    assert aps.kb_dir() == tmp_path / "K"
    assert json.loads((tmp_path / "app_settings.json").read_text())["tickets_dir"] == str(tmp_path / "T")

def test_partial_file_falls_back(tmp_path, monkeypatch):
    aps = _fresh(tmp_path, monkeypatch)
    (tmp_path / "app_settings.json").write_text(json.dumps({"tickets_dir": str(tmp_path / "T")}))
    assert aps.tickets_dir() == tmp_path / "T"
    assert aps.kb_dir() == tmp_path / "library" / "kb"   # missing key -> default
