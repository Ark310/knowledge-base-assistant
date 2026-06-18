import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import gui


def test_asset_path_resolves_in_source_mode():
    p = gui._asset_path("contoso_logo.png")
    assert p is not None
    assert Path(p).exists()


def test_asset_path_missing_returns_none():
    assert gui._asset_path("no_such_asset_xyz.png") is None


def test_logo_pngs_committed():
    root = Path(gui.__file__).parent.parent.parent
    assert (root / "assets" / "contoso_logo.png").exists()
    assert (root / "assets" / "contoso_logo_lg.png").exists()
