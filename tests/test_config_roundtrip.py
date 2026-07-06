import sys, importlib.util
from pathlib import Path
import tempfile
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.config_writer import update_release_notes_urls

CONFIG_TEMPLATE = '''\
PRODUCTS = {
    "tradedesk": {
        "display_name": "TradeDesk",
        "space_key": "releasenotes",
        "release_notes_url": "",
    },
    "web4": {
        "display_name": "Web4",
        "space_key": "ReleaseNotesWeb4",
        "release_notes_url": "",
    },
}
'''


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("tmp_config", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_update_writes_urls():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.py"
        cfg.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        update_release_notes_urls(cfg, {
            "tradedesk": "https://help.contoso.example/display/releasenotes",
            "web4": "https://help.contoso.example/display/ReleaseNotesWeb4",
        })
        mod = _load(cfg)
        assert mod.PRODUCTS["tradedesk"]["release_notes_url"] == "https://help.contoso.example/display/releasenotes"
        assert mod.PRODUCTS["web4"]["release_notes_url"] == "https://help.contoso.example/display/ReleaseNotesWeb4"


def test_update_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.py"
        cfg.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        urls = {"tradedesk": "https://x/fx", "web4": "https://x/w4"}
        update_release_notes_urls(cfg, urls)
        update_release_notes_urls(cfg, urls)  # second time must not corrupt
        mod = _load(cfg)
        assert mod.PRODUCTS["tradedesk"]["release_notes_url"] == "https://x/fx"
        assert mod.PRODUCTS["web4"]["release_notes_url"] == "https://x/w4"


def test_update_only_touches_named_products():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.py"
        cfg.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        update_release_notes_urls(cfg, {"tradedesk": "https://x/fx"})
        mod = _load(cfg)
        assert mod.PRODUCTS["tradedesk"]["release_notes_url"] == "https://x/fx"
        assert mod.PRODUCTS["web4"]["release_notes_url"] == ""  # untouched
