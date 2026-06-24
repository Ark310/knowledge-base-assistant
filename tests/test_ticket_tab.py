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
