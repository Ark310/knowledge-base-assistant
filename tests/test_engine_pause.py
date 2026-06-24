import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.control import RunControl
import scraper.engine as engine
import scraper.kb_engine as kb_engine

def test_runcontrol_is_cancelled_compat():
    c = RunControl()
    assert c.is_cancelled() is False
    c.cancel()
    assert c.is_cancelled() is True

def test_engine_cancellationtoken_is_runcontrol():
    assert engine.CancellationToken is RunControl

def test_kbengine_output_base_default_and_override(tmp_path):
    from scraper.kb_config import KB_LIBRARY_BASE
    assert kb_engine.KBEngine().output_base == KB_LIBRARY_BASE
    assert kb_engine.KBEngine(output_base=tmp_path / "kb").output_base == tmp_path / "kb"

def test_kbengine_scrape_family_scopes_to_family():
    """scrape_family iterates only the spaces for the given product_label, not all 43."""
    from scraper.kb_config import KB_PRODUCT_GROUPS
    engine = kb_engine.KBEngine()
    scraped_keys = []
    rebuilt = []
    reported = []

    engine._scrape_one    = lambda space_key, force, with_index_rebuild, action_label: (
        scraped_keys.append(space_key) or {"discovered": 0, "new": 0, "skipped": 0, "failed": 0}
    )
    engine.rebuild_indexes = lambda: rebuilt.append(1)
    engine._write_report  = lambda r: reported.append(r)

    label = "TradeDesk KB"
    engine.scrape_family(label)

    expected = [s["space_key"] for s in KB_PRODUCT_GROUPS[label]]
    assert scraped_keys == expected
    assert len(scraped_keys) < 43  # sanity-check: not the full KB
    assert rebuilt  # index rebuilt after the family run

def test_paused_runcontrol_then_cancel_releases():
    # wait_if_paused returns once cancelled even while paused (engines won't hang on close)
    import threading, time
    c = RunControl(); c.pause()
    released = []
    threading.Thread(target=lambda: (c.wait_if_paused(), released.append(1)), daemon=True).start()
    time.sleep(0.2); assert not released
    c.cancel(); time.sleep(0.3); assert released
