# tests/test_icon_asset.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from PIL import Image

ICO = Path(__file__).parent.parent / "assets" / "scraper_icon.ico"

def test_icon_exists_and_valid():
    assert ICO.exists(), "run _make_scraper_icon.py to generate the icon"
    im = Image.open(ICO)
    assert im.format == "ICO"
    sizes = im.info.get("sizes") or {im.size}
    assert any(max(s) >= 64 for s in sizes), "icon must include a >=64px size"
