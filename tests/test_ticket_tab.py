import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QTableWidgetItem
_app = QApplication.instance() or QApplication([])
from scraper.ticket_tab import TicketTab
import scraper.run_registry as run_registry


@pytest.fixture(autouse=True)
def _reset_run_registry():
    """Keep the module-level single-run registry clean between tests — it is
    shared global state, so a test that acquires and doesn't release would
    otherwise leak into unrelated tests run later in the same session."""
    run_registry.release(run_registry.owner() or "")
    yield
    run_registry.release(run_registry.owner() or "")

def test_workers_spinbox_1_to_10_default_4():
    t = TicketTab()
    assert t.spn_workers.minimum() == 1
    assert t.spn_workers.maximum() == 10
    assert t.spn_workers.value() == 4

def test_has_pause_and_settings_buttons():
    t = TicketTab()
    assert t.btn_pause is not None and t.btn_settings is not None
    assert t.btn_start.objectName() == "PrimaryButton"

def test_table_has_title_and_files_columns():
    t = TicketTab()
    headers = [t.table.horizontalHeaderItem(i).text() for i in range(t.table.columnCount())]
    assert headers == ["Ticket #", "Status", "Title", "Files"]

def test_no_inline_credential_fields():
    t = TicketTab()
    for attr in ("inp_pass", "inp_user", "inp_url"):
        assert not hasattr(t, attr), f"{attr} must move to Settings"
    assert hasattr(t, "lbl_creds")

def test_on_ticket_meta_populates_title_and_files():
    t = TicketTab()
    # seed a row for ticket 76511 (mirror how _start builds rows)
    t.table.setRowCount(0)
    t.table.insertRow(0)
    t.table.setItem(0, 0, QTableWidgetItem("#76511"))
    t._ticket_rows = {"76511": 0}
    t._on_ticket_meta("76511", "APA ONE - Org config", 2)
    assert t.table.item(0, 2).text() == "APA ONE - Org config"
    assert t.table.item(0, 3).text() == "2"

def test_shutdown_no_worker_is_noop():
    t = TicketTab()
    t.shutdown()  # no worker running -> must not raise

def test_shutdown_cancels_and_waits_running_worker():
    # shutdown() must cancel the control (releases a paused worker) and join the thread,
    # so closing the window during a paused scrape can't destroy a live QThread.
    t = TicketTab()
    class _FakeCtl:
        cancelled = False
        def cancel(self): self.cancelled = True
    class _FakeWorker:
        waited = False
        def isRunning(self): return True
        def wait(self, ms): self.waited = True; return True
    t._control = _FakeCtl()
    t._worker = _FakeWorker()
    t.shutdown()
    assert t._control.cancelled and t._worker.waited


def test_ticket_tab_passes_browser_mode_to_worker(tmp_path, monkeypatch):
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    s.set_browser_mode("multi")
    import scraper.ticket_tab as tt
    import scraper.ticket_settings as ts_mod
    captured = {}

    class _NoOp:
        """Callable no-op that also acts as a signal (has .connect)."""
        def __call__(self, *a, **k): pass
        def connect(self, *a, **k): pass

    class _StubWorker:
        def __init__(self, *a, **k):
            captured.update(k)
            self.control = k.get("control")

        def __getattr__(self, n):
            return _NoOp()  # signals/.start/isRunning — all no-op

    monkeypatch.setattr(tt, "AsyncTicketWorker", _StubWorker)
    monkeypatch.setattr(ts_mod, "load", lambda: {"portal_url": "https://x", "username": "u"})
    monkeypatch.setattr(ts_mod, "load_password", lambda u: "pw")

    tab = tt.TicketTab()
    tab.inp_tickets.setText("76511")   # real input widget (QLineEdit)
    tab._start()
    assert captured.get("mode") == "multi"


def test_ticket_tab_contoso_passes_portal_kind(tmp_path, monkeypatch):
    """TicketTab(portal_kind='contoso') constructs offscreen and _start passes
    portal_kind='contoso' to AsyncTicketWorker."""
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    import scraper.ticket_tab as tt
    import scraper.ticket_settings as ts_mod
    captured = {}

    class _NoOp:
        """Callable no-op that also acts as a signal (has .connect)."""
        def __call__(self, *a, **k): pass
        def connect(self, *a, **k): pass

    class _StubWorker:
        def __init__(self, *a, **k):
            captured.update(k)
            self.control = k.get("control")

        def __getattr__(self, n):
            return _NoOp()  # signals/.start/isRunning — all no-op

    monkeypatch.setattr(tt, "AsyncTicketWorker", _StubWorker)
    monkeypatch.setattr(ts_mod, "load", lambda: {"portal_url": "https://x", "username": "u"})
    monkeypatch.setattr(ts_mod, "load_password", lambda u: "pw")

    tab = tt.TicketTab(portal_kind="contoso", default_url="https://support.contoso.example")
    tab.inp_tickets.setText("76511")
    tab._start()
    assert captured.get("portal_kind") == "contoso"


def test_start_blocked_while_registry_busy(monkeypatch):
    """Single-run guard (R7): if another tab already owns the registry, _start()
    must refuse — no worker created, registry owner unchanged — and warn via
    QMessageBox (stubbed to a recorder, following this file's dialog-stub pattern)."""
    import scraper.ticket_tab as tt

    warnings = []
    monkeypatch.setattr(
        tt.QMessageBox, "warning",
        lambda *a, **k: warnings.append(a) or None,
    )

    run_registry.acquire("other")

    tab = tt.TicketTab()
    tab.inp_tickets.setText("76511")   # valid-looking input
    tab._start()

    assert tab._worker is None
    assert run_registry.owner() == "other"
    assert len(warnings) == 1


def test_alert_slot_shows_nonmodal_box():
    """_on_alert must build+show a non-modal QMessageBox and keep a reference
    to it (so it isn't garbage-collected while the engine keeps running)."""
    t = TicketTab()
    t._on_alert("error", "T", "B")
    assert t._alert_box is not None
    assert t._alert_box.windowTitle() == "T"


def test_worker_done_releases_registry():
    """_worker_thread_done runs for every outcome (including engine crash) and
    must release the registry so another tab can start a scrape."""
    t = TicketTab()
    run_registry.acquire(t._run_name)
    t._worker_thread_done()
    assert run_registry.owner() is None


def _stub_worker_env(monkeypatch, tmp_path):
    """Shared setup: stub AsyncTicketWorker + creds so _start() never touches
    a real browser/thread (follows the existing worker-stub pattern above)."""
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    import scraper.ticket_tab as tt
    import scraper.ticket_settings as ts_mod

    class _NoOp:
        """Callable no-op that also acts as a signal (has .connect)."""
        def __call__(self, *a, **k): pass
        def connect(self, *a, **k): pass

    class _StubWorker:
        def __init__(self, *a, **k):
            pass
        def __getattr__(self, n):
            return _NoOp()  # signals/.start/isRunning — all no-op

    monkeypatch.setattr(tt, "AsyncTicketWorker", _StubWorker)
    monkeypatch.setattr(ts_mod, "load", lambda: {"portal_url": "https://x", "username": "u"})
    monkeypatch.setattr(ts_mod, "load_password", lambda u: "pw")
    return tt


def test_big_batch_skips_row_precreation(tmp_path, monkeypatch):
    """A batch bigger than BIG_BATCH_ROWS must not pre-create table rows —
    bug-115 froze the GUI pre-creating 19k QTableWidget rows. Rows appear
    lazily as tickets complete."""
    tt = _stub_worker_env(monkeypatch, tmp_path)

    tab = tt.TicketTab()
    tab.inp_tickets.setText(f"1-{tt.TicketTab.BIG_BATCH_ROWS + 1}")
    tab._start()

    assert tab.table.rowCount() == 0
    assert tab._ticket_rows == {}
    assert tab._big_batch is True

    tab._on_ticket_done("55555", "ok")

    assert tab.table.rowCount() == 1
    assert tab.table.item(0, 0).text() == "#55555"
    assert tab.table.item(0, 1).text() == "Saved"


def test_small_batch_still_precreates_rows(tmp_path, monkeypatch):
    """Existing behavior preserved for ordinary-sized batches."""
    tt = _stub_worker_env(monkeypatch, tmp_path)

    tab = tt.TicketTab()
    tab.inp_tickets.setText("1,2,3,4,5")
    tab._start()

    assert tab.table.rowCount() == 5
    assert tab._big_batch is False
    assert set(tab._ticket_rows) == {"1", "2", "3", "4", "5"}


def test_log_lines_are_buffered_then_flushed():
    """_emit_log must only buffer — the GUI append is deferred to a timer-driven
    _flush_log (bug-115: per-line QPlainTextEdit appends froze the GUI on a
    30k-ticket run). _flush_log itself now issues one appendHtml PER LINE
    (wrapped in setUpdatesEnabled(False)/True for a single repaint) so that
    each line gets its own QTextBlock and MAX_LOG_LINES caps LINES, not
    flushes — assert blockCount grows 1:1 with lines flushed."""
    t = TicketTab()
    start_blocks = t.log_pane.blockCount()

    for i in range(50):
        t._emit_log("info", f"line {i}")

    assert t.log_pane.blockCount() == start_blocks
    assert len(t._log_buf) == 50

    t._flush_log()

    assert t._log_buf == []
    # Verified empirically: a fresh QPlainTextEdit starts with ONE empty
    # block; appendHtml-ing 50 lines consumes that block for the first line
    # and adds one new block per subsequent line, landing at exactly 50 —
    # not 51 — blocks (one per line, not one-plus-the-original-empty-block).
    assert t.log_pane.blockCount() == 50
    text = t.log_pane.toPlainText()
    assert len(text.split("\n")) == 50
    assert "line 0" in text and "line 49" in text


def test_live_worker_change_updates_control_target():
    """Live worker slider (Task 7 wiring): while a scrape is running, moving
    spn_workers must push the new value onto RunControl.target_workers (no
    restart) and update the monitor's workers label. Worker-stub pattern
    mirrors test_shutdown_cancels_and_waits_running_worker's _FakeWorker."""
    t = TicketTab()

    class _FakeRunningWorker:
        def isRunning(self):
            return True

    t._worker = _FakeRunningWorker()
    t.spn_workers.setValue(2)

    assert t._control.target_workers == 2


def test_priority_combo_defaults_and_applies_on_change(tmp_path, monkeypatch):
    """cmb_priority mirrors app_settings.priority() on init and, when changed,
    persists the new level + calls procctl.apply_priority."""
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    import scraper.ticket_tab as tt
    import scraper.procctl as procctl_mod

    calls = []
    monkeypatch.setattr(procctl_mod, "apply_priority", lambda level: calls.append(level) or 3)

    t = tt.TicketTab()
    assert t.cmb_priority.currentText() == "Normal"

    t.cmb_priority.setCurrentText("High")

    assert calls == ["high"]
    assert s.priority() == "high"


def test_worker_spinbox_stays_enabled_while_running():
    """Live worker slider requires the spinbox to remain editable during a
    run (bug-fix vs. the old setEnabled(not running))."""
    t = TicketTab()
    t._set_running(True)
    assert t.spn_workers.isEnabled()
