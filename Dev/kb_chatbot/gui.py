"""V2.2 KB Chatbot GUI. No API key. Claude Code preflight on startup."""
from __future__ import annotations
import sys
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QTextCursor, QAction, QFont, QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QPlainTextEdit, QLineEdit, QToolBar,
    QStatusBar, QMessageBox, QDialog, QDialogButtonBox, QFormLayout,
    QFileDialog, QProgressBar,
)

from Dev.kb_chatbot import config, settings as settings_mod
from Dev.kb_chatbot.chat.orchestrator import Deps, handle_turn
from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider, ClaudeCodeNotFoundError
from Dev.kb_chatbot.retriever import Retriever, Filters

config.STATE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("kb_chatbot.gui")


def _append_usage(turn: Turn) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": turn.ts, "kind": turn.kind, "model": turn.model,
        "tokens_in": turn.tokens_in, "tokens_out": turn.tokens_out,
        "latency_ms": turn.latency_ms, "retrieved_ids": turn.retrieved_ids,
        "citations": turn.citations,
    }
    with open(config.USAGE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class TurnWorker(QThread):
    def __init__(self, user_msg, session, filters, default_model, deps):
        super().__init__()
        self.user_msg = user_msg
        self.session = session
        self.filters = filters
        self.default_model = default_model
        self.deps = deps
        self.signals = WorkerSignals()
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            turn = handle_turn(self.user_msg, self.session, self.filters,
                                self.default_model, deps=self.deps)
            if self._cancel:
                turn = Turn(role="assistant", kind="abstain", content="Cancelled.")
                self.session.add(turn)
            self.signals.finished.emit(turn)
        except Exception as exc:
            log.exception("Turn failed")
            self.signals.failed.emit(str(exc))
        # Note: retriever is shared across turns — do not close it here


class IngestWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, library_path, chroma_path):
        super().__init__()
        self.library_path = library_path
        self.chroma_path = chroma_path

    def run(self):
        try:
            report = ingest(self.library_path, self.chroma_path,
                             on_progress=lambda d, t: self.progress.emit(d, t))
            self.finished.emit(report)
        except Exception as exc:
            log.exception("Ingest failed")
            self.failed.emit(str(exc))


class InitWorker(QThread):
    """Loads ML models and warms up the Claude SDK client in the background.
    Emits ready(retriever) when complete so the GUI can unlock the input."""
    ready = Signal(object)   # emits the loaded Retriever
    status = Signal(str)     # progress messages for the status bar
    failed = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def run(self):
        try:
            self.status.emit("⟳ Initialising — loading models…")
            retriever = Retriever(
                config.CHROMA_DIR,
                confidence_floor=self.settings.confidence_floor,
            )
            self.status.emit("⟳ Initialising — warming up Claude…")
            try:
                from Dev.kb_chatbot.prompt import build_system_prompt
                ClaudeCodeProvider().warm_up(build_system_prompt(), self.settings.default_model)
            except ClaudeCodeNotFoundError as exc:
                log.warning("Skipping LLM warm-up: %s", exc)
            self.ready.emit(retriever)
        except Exception as exc:
            log.exception("InitWorker failed")
            self.failed.emit(str(exc))


class SettingsDialog(QDialog):
    def __init__(self, parent, current):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 180)
        form = QFormLayout(self)
        self.lib_edit = QLineEdit(str(current.library_path))
        self.lib_btn = QPushButton("Browse…")
        self.lib_btn.clicked.connect(self._pick_dir)
        lib_row = QHBoxLayout(); lib_row.addWidget(self.lib_edit); lib_row.addWidget(self.lib_btn)
        lib_w = QWidget(); lib_w.setLayout(lib_row)
        self.model_box = QComboBox()
        for label, ident in config.AVAILABLE_MODELS.items():
            self.model_box.addItem(label, ident)
        idx = self.model_box.findData(current.default_model)
        if idx >= 0:
            self.model_box.setCurrentIndex(idx)
        form.addRow("Library path:", lib_w)
        form.addRow("Default model:", self.model_box)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Pick library directory", self.lib_edit.text())
        if d:
            self.lib_edit.setText(d)

    def values(self):
        return settings_mod.Settings(
            library_path=Path(self.lib_edit.text()),
            default_model=self.model_box.currentData(),
            confidence_floor=config.CONFIDENCE_FLOOR,
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contoso KB Chatbot")
        self.resize(1100, 780)
        self.settings = settings_mod.load_settings()
        self.session = Session.new()
        self.worker: Optional[TurnWorker] = None
        self.ingest_worker: Optional[IngestWorker] = None
        self._retriever: Optional[Retriever] = None
        self._today_queries = 0
        self._today_tokens = 0
        self._build_ui()
        # Window shows immediately; models + LLM warm-up load in background
        self._set_chat_enabled(False)
        self.statusBar().showMessage("⟳ Initialising — please wait…")
        self._start_init_worker()

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        tb = QToolBar(); tb.setMovable(False); self.addToolBar(tb)
        self._act_reindex = QAction("Reindex", self); tb.addAction(self._act_reindex)
        self._act_reindex.setToolTip("Run after adding new articles to the knowledge base")
        self._act_settings = QAction("Settings", self); tb.addAction(self._act_settings)
        self._act_clear = QAction("Clear chat", self); tb.addAction(self._act_clear)
        tb.addSeparator()
        self._act_stop = QAction("⏹ STOP", self); tb.addAction(self._act_stop)
        self._act_logs = QAction("View logs", self); tb.addAction(self._act_logs)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Product:"))
        self.product_box = QComboBox()
        self.product_box.addItem("Any", "")
        for p in config.PRODUCTS:
            self.product_box.addItem(config.PRODUCT_DISPLAY.get(p, p), p)
        filter_row.addWidget(self.product_box)
        filter_row.addWidget(QLabel("Model:"))
        self.model_box = QComboBox()
        for label, ident in config.AVAILABLE_MODELS.items():
            self.model_box.addItem(label, ident)
        idx = self.model_box.findData(self.settings.default_model)
        if idx >= 0:
            self.model_box.setCurrentIndex(idx)
        filter_row.addWidget(self.model_box)
        filter_row.addStretch()
        outer.addLayout(filter_row)

        self.chat_view = QPlainTextEdit(); self.chat_view.setReadOnly(True)
        self.chat_view.setFont(QFont("Consolas", 10))
        outer.addWidget(self.chat_view, stretch=1)

        self.progress = QProgressBar(); self.progress.setVisible(False)
        outer.addWidget(self.progress)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask a question about the Contoso KB…")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input); input_row.addWidget(self.send_btn)
        outer.addLayout(input_row)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Log: {config.LOG_FILE}")

        self._act_reindex.triggered.connect(self._reindex)
        self._act_settings.triggered.connect(self._open_settings)
        self._act_clear.triggered.connect(self._clear_chat)
        self._act_stop.triggered.connect(self._stop)
        self._act_logs.triggered.connect(self._open_logs)
        self._set_inputs_enabled(True)

    def _start_init_worker(self):
        self._init_worker = InitWorker(self.settings)
        self._init_worker.ready.connect(self._on_init_ready)
        self._init_worker.status.connect(self.statusBar().showMessage)
        self._init_worker.failed.connect(self._on_init_failed)
        self._init_worker.start()

    @Slot(object)
    def _on_init_ready(self, retriever):
        self._retriever = retriever
        self._set_chat_enabled(True)
        self.statusBar().showMessage("Ready")
        self._append("system", "Ready. Type a question below.", "#1b5e20", "SYSTEM:")

    @Slot(str)
    def _on_init_failed(self, err):
        self.statusBar().showMessage(f"Init failed: {err}")
        self._append("system", f"Initialisation failed: {err}", "#c62828", "ERROR:")

    def _set_chat_enabled(self, enabled: bool):
        self.input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)

    def _append(self, role, text, colour, tag):
        ts = datetime.now().strftime("%H:%M:%S")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat(); fmt.setForeground(QColor(colour))
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"{ts} {tag:9s} {text}\n\n", fmt)
        self.chat_view.setTextCursor(cursor)
        self.chat_view.ensureCursorVisible()

    def _send(self):
        msg = self.input.text().strip()
        if not msg or self.worker or self._retriever is None:
            return
        self.input.clear()
        self._set_inputs_enabled(False)
        self._append("user", msg, "#0d47a1", "YOU:")

        try:
            llm = ClaudeCodeProvider()
        except ClaudeCodeNotFoundError as exc:
            self._append("system", str(exc), "#c62828", "ERROR:")
            self._set_inputs_enabled(True)
            return

        deps = Deps(retriever=self._retriever, llm=llm, usage_logger=_append_usage)
        filters = Filters(product=self.product_box.currentData() or None)
        model = self.model_box.currentData()
        self.worker = TurnWorker(msg, self.session, filters, model, deps)
        self.worker.signals.finished.connect(self._on_turn_done)
        self.worker.signals.failed.connect(self._on_turn_failed)
        self.worker.start()

    @Slot(object)
    def _on_turn_done(self, turn):
        colour = "#212121"; tag = "AI:"
        if turn.kind == "abstain":
            colour, tag = "#5d4037", "ABSTAIN:"
        elif turn.kind == "clarification":
            colour, tag = "#ef6c00", "CLARIFY:"
        self._append("ai", turn.content, colour, tag)
        self._today_queries += 1
        self._today_tokens += turn.tokens_in + turn.tokens_out
        self.statusBar().showMessage(
            f"Today: {self._today_queries} queries · {self._today_tokens} tokens · Log: {config.LOG_FILE}"
        )
        self.worker = None
        self._set_inputs_enabled(True)

    @Slot(str)
    def _on_turn_failed(self, err):
        self._append("system", f"Error: {err}", "#c62828", "ERROR:")
        self.worker = None
        self._set_inputs_enabled(True)

    def _stop(self):
        if self.worker:
            self.worker.cancel()

    def _open_settings(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QDialog.Accepted:
            self.settings = dlg.values()
            settings_mod.save_settings(self.settings)
            self._append("system", "Settings saved.", "#1b5e20", "SYSTEM:")

    def _clear_chat(self):
        self.chat_view.clear()
        self.session = Session.new()
        try:
            ClaudeCodeProvider.reset_conversation()
        except Exception:
            log.exception("LLM conversation reset failed (non-fatal)")

    def _open_logs(self):
        import subprocess
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer.exe", str(config.STATE_DIR)])

    def _reindex(self):
        if self.ingest_worker:
            return
        self.progress.setVisible(True); self.progress.setValue(0)
        self._set_inputs_enabled(False)
        self.ingest_worker = IngestWorker(self.settings.library_path, config.CHROMA_DIR)
        self.ingest_worker.progress.connect(self._on_ingest_progress)
        self.ingest_worker.finished.connect(self._on_ingest_done)
        self.ingest_worker.failed.connect(self._on_ingest_failed)
        self.ingest_worker.start()
        self._append("system", f"Reindex started from {self.settings.library_path}", "#1b5e20", "SYSTEM:")

    @Slot(int, int)
    def _on_ingest_progress(self, done, total):
        if total:
            self.progress.setValue(int(done * 100 / total))

    @Slot(object)
    def _on_ingest_done(self, report):
        self.progress.setVisible(False)
        self._append("system",
            f"Reindex complete: {report.articles_seen} articles, {report.chunks_created} chunks, {report.duration_s:.1f}s",
            "#1b5e20", "SYSTEM:")
        self.ingest_worker = None
        self._set_inputs_enabled(True)

    @Slot(str)
    def _on_ingest_failed(self, err):
        self.progress.setVisible(False)
        self._append("system", f"Reindex failed: {err}", "#c62828", "ERROR:")
        self.ingest_worker = None
        self._set_inputs_enabled(True)

    def _set_inputs_enabled(self, enabled: bool):
        if self._retriever is not None:  # chat stays locked until init completes
            self._set_chat_enabled(enabled)
        for w in (self._act_reindex, self._act_settings, self._act_clear):
            w.setEnabled(enabled)
        self._act_stop.setEnabled(not enabled)

    def closeEvent(self, event):
        if self.worker or self.ingest_worker:
            reply = QMessageBox.question(self, "Quit?",
                "A task is running. Quit anyway?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore(); return
            if self.worker:
                self.worker.cancel(); self.worker.wait(5_000)
        if getattr(self, "_init_worker", None) and self._init_worker.isRunning():
            self._init_worker.wait(2_000)
        if self._retriever is not None:
            try:
                self._retriever.close()
            except Exception:
                pass
        try:
            self.session.save(config.CHATS_DIR)
        except Exception:
            log.exception("Session save failed on close")
        try:
            ClaudeCodeProvider.shutdown()
        except Exception:
            log.exception("ClaudeCodeProvider shutdown failed")
        event.accept()


def _preflight_claude_code() -> Optional[str]:
    if shutil.which("claude"):
        return None
    return ("Claude Code is required.\n\n"
            "Install from https://claude.com/claude-code, run `claude login`, "
            "and re-launch this app.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Contoso KB Chatbot")
    err = _preflight_claude_code()
    if err:
        QMessageBox.critical(None, "Claude Code missing", err)
        sys.exit(1)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
