import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.config import APP_VERSION

def test_app_version_is_4_0_1():
    assert APP_VERSION == "4.0.1"
