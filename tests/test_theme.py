# tests/test_theme.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper import theme

def test_palette_has_brand_colors():
    for k in ("brand", "warm", "bg", "surface", "text"):
        assert k in theme.PALETTE and theme.PALETTE[k].startswith("#")
    assert theme.PALETTE["brand"].lower() == "#51639e"

def test_stylesheet_references_brand_and_font():
    qss = theme.app_stylesheet()
    assert isinstance(qss, str) and len(qss) > 100
    assert theme.PALETTE["brand"] in qss
    assert "QPushButton" in qss and "PrimaryButton" in qss

def test_font_stack_is_segoe():
    assert "Segoe UI" in theme.FONT_STACK
