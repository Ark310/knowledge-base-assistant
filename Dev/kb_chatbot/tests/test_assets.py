import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot import gui

_ASSETS = Path(gui.__file__).parent.parent.parent / "assets"
needs_assets = pytest.mark.skipif(not (_ASSETS / "contoso_logo.png").exists(),
                                  reason="branding assets are not shipped in the public repo")


@needs_assets
def test_asset_path_resolves_in_source_mode():
    p = gui._asset_path("contoso_logo.png")
    assert p is not None
    assert Path(p).exists()


def test_asset_path_missing_returns_none():
    assert gui._asset_path("no_such_asset_xyz.png") is None


@needs_assets
def test_logo_pngs_committed():
    root = Path(gui.__file__).parent.parent.parent
    assert (root / "assets" / "contoso_logo.png").exists()
    assert (root / "assets" / "contoso_logo_lg.png").exists()
