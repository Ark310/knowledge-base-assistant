"""V2.6 KB Chatbot GUI. No API key. Provider preflight on startup. One-folder offline build."""
from __future__ import annotations
import sys
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
if getattr(sys, "frozen", False):
    _models = os.path.join(os.path.dirname(sys.executable), "models", "huggingface")
    if os.path.isdir(_models):
        os.environ.setdefault("HF_HOME", _models)
import json
import logging
import random
import shutil
import html as html_module
import re as re_module
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QTextCursor, QAction, QFont, QColor, QTextCharFormat, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTextBrowser, QLineEdit, QToolBar,
    QStatusBar, QMessageBox, QDialog, QDialogButtonBox, QFormLayout,
    QFileDialog, QProgressBar, QPlainTextEdit, QInputDialog,
    QTableWidget, QTableWidgetItem,
)

from Dev.kb_chatbot import config, settings as settings_mod
from Dev.kb_chatbot.chat.query_rewriter import make_rewriter
from Dev.kb_chatbot.chat.orchestrator import Deps, handle_turn
from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider, ClaudeCodeNotFoundError
from Dev.kb_chatbot.llm.codex_provider import CodexProvider, CodexNotFoundError, codex_login_ok
from Dev.kb_chatbot.retriever import Retriever, Filters

config.STATE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("kb_chatbot.gui")

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_TEXT_EXTS  = {".md", ".txt", ".json", ".log"}
_ALL_EXTS   = _IMAGE_EXTS | _TEXT_EXTS
_MAX_IMAGE_BYTES = 4 * 1024 * 1024   # 4 MB (Claude image limit)
_MAX_TEXT_BYTES  = 1 * 1024 * 1024   # 1 MB cap for text files (prompt truncates at 20k chars)
_MAX_ATTACHMENTS = 5
_MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}

# Matches [Title](https://...) — mirrors citations._CITE_RE, handles parenthesised URLs
_LINK_RE = re_module.compile(r'\[([^\]]+)\]\((https?://(?:[^()\s]|\([^()\s]*\))+)\)')

THINKING_WORDS = [
    "Pondering", "Rummaging the KB", "Connecting dots", "Cross-referencing",
    "Consulting the archives", "Reticulating splines", "Reading the manuals",
    "Chasing citations", "Untangling deals", "Asking the librarian",
    "Double-checking sources", "Brewing an answer",
]
INIT_WORDS = ["Waking up the librarian", "Stretching the neural nets", "Dusting off the archives"]
REPHRASE_TEXT = "Rephrasing your question for a better search"


def build_provider(provider_id: str):
    """Construct the LLM provider for the given provider id."""
    if provider_id == "openai":
        return CodexProvider()
    return ClaudeCodeProvider()


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
    progress = Signal(str)


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
            self.status.emit("✦ Loading search models…")
            retriever = Retriever(
                config.CHROMA_DIR,
                confidence_floor=self.settings.confidence_floor,
            )
            provider_id = getattr(self.settings, "default_provider", "claude")
            display = config.PROVIDERS.get(provider_id, config.PROVIDERS["claude"])["display"]
            self.status.emit(f"✦ Warming up {display}…")
            try:
                if provider_id == "claude":
                    from Dev.kb_chatbot.prompt import build_system_prompt
                    ClaudeCodeProvider().warm_up(build_system_prompt(), self.settings.default_model)
                # Codex exec is cold-start per call — nothing to warm.
            except (ClaudeCodeNotFoundError, CodexNotFoundError) as exc:
                log.warning("Skipping LLM warm-up: %s", exc)
            self.ready.emit(retriever)
        except Exception as exc:
            log.exception("InitWorker failed")
            self.failed.emit(str(exc))


class ThinkingIndicator(QLabel):
    """Claude-style animated status: '✦ <word>…' with cycling words and pulsing dots."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("color:#7e57c2; font-style:italic; padding:2px 8px;")
        self.setVisible(False)
        self._words: list[str] = []
        self._word_idx = 0
        self._dots = 1
        self._pinned: Optional[str] = None
        self._word_timer = QTimer(self)
        self._word_timer.setInterval(2500)
        self._word_timer.timeout.connect(self._next_word)
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(400)
        self._dot_timer.timeout.connect(self._pulse)

    def start(self, words: list[str]):
        self._words = list(words)
        random.shuffle(self._words)
        self._word_idx = 0
        self._dots = 1
        self._pinned = None
        self._render()
        self.setVisible(True)
        self._word_timer.start()
        self._dot_timer.start()

    def pin(self, text: str):
        """Hold one status (e.g. the rewrite stage) instead of cycling."""
        self._pinned = text
        self._render()

    def stop(self):
        self._word_timer.stop()
        self._dot_timer.stop()
        self.setVisible(False)

    def _next_word(self):
        if self._pinned is None and self._words:
            self._word_idx = (self._word_idx + 1) % len(self._words)
            self._render()

    def _pulse(self):
        self._dots = self._dots % 3 + 1
        self._render()

    def _render(self):
        word = self._pinned if self._pinned is not None else (
            self._words[self._word_idx] if self._words else "Thinking")
        self.setText(f"✦ {word}{'.' * self._dots}")


class SettingsDialog(QDialog):
    def __init__(self, parent, current):
        super().__init__(parent)
        self._current = current
        self.setWindowTitle("Settings")
        self.resize(560, 180)
        form = QFormLayout(self)
        self.lib_edit = QLineEdit(str(current.library_path))
        self.lib_btn = QPushButton("Browse…")
        self.lib_btn.clicked.connect(self._pick_dir)
        lib_row = QHBoxLayout(); lib_row.addWidget(self.lib_edit); lib_row.addWidget(self.lib_btn)
        lib_w = QWidget(); lib_w.setLayout(lib_row)
        self.provider_box = QComboBox()
        for pid, prov in config.PROVIDERS.items():
            self.provider_box.addItem(prov["display"], pid)
        ppidx = self.provider_box.findData(getattr(current, "default_provider", "claude"))
        if ppidx >= 0:
            self.provider_box.setCurrentIndex(ppidx)
        self.model_box = QComboBox()
        self._fill_models(getattr(current, "default_provider", "claude"), current.default_model)
        self.provider_box.currentIndexChanged.connect(self._on_dialog_provider_changed)
        form.addRow("Library path:", lib_w)
        form.addRow("Default AI provider:", self.provider_box)
        form.addRow("Default model:", self.model_box)
        self.usage_btn = QPushButton("View Token Usage…")
        self.usage_btn.clicked.connect(self._open_usage)
        form.addRow(self.usage_btn)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _open_usage(self):
        session_start = getattr(self.parent(), "_session_start_ts", "")
        TokenUsageDialog(self, session_start).exec()

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Pick library directory", self.lib_edit.text())
        if d:
            self.lib_edit.setText(d)

    def _fill_models(self, provider_id: str, select_model: str = ""):
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for label, ident in config.models_for(provider_id).items():
            self.model_box.addItem(label, ident)
        idx = self.model_box.findData(select_model or config.default_model_for(provider_id))
        self.model_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.model_box.blockSignals(False)

    def _on_dialog_provider_changed(self, _index: int):
        self._fill_models(self.provider_box.currentData())

    def values(self):
        return settings_mod.Settings(
            library_path=Path(self.lib_edit.text()),
            default_model=self.model_box.currentData(),
            confidence_floor=config.CONFIDENCE_FLOOR,
            learn_mode_hash=self._current.learn_mode_hash,
            model_explicitly_set=True,
            default_provider=self.provider_box.currentData(),
        )


class TokenUsageDialog(QDialog):
    """Read-only token usage + API-equivalent cost breakdown from usage.jsonl."""

    def __init__(self, parent, session_start: str):
        super().__init__(parent)
        from Dev.kb_chatbot import usage_stats
        self.setWindowTitle("Token Usage")
        self.resize(640, 480)
        layout = QVBoxLayout(self)

        records = usage_stats.load_usage(config.USAGE_FILE)
        s = usage_stats.summarize(records, session_start=session_start)

        def fmt(n: int) -> str:
            return f"{n:,}"

        avg_in = s.total_in // s.total_queries if s.total_queries else 0
        avg_out = s.total_out // s.total_queries if s.total_queries else 0
        avg_cost = s.total_cost / s.total_queries if s.total_queries else 0.0
        summary = QLabel(
            f"<b>All time:</b> {fmt(s.total_in)} in · {fmt(s.total_out)} out · ≈ ${s.total_cost:.2f}<br>"
            f"<b>This session:</b> {fmt(s.session_in)} in · {fmt(s.session_out)} out · ≈ ${s.session_cost:.4f}<br>"
            f"<b>Per query avg:</b> {fmt(avg_in)} in · {fmt(avg_out)} out · ≈ ${avg_cost:.4f}<br>"
            f"<b>Queries:</b> {s.total_queries} all-time · {s.session_queries} this session"
        )
        layout.addWidget(summary)

        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["Time", "Kind", "Model", "In", "Out", "Cost"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        rows = list(reversed(records))  # newest first
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            ts = (r.get("ts") or "")[11:19]  # HH:MM:SS
            model = config.MODEL_DISPLAY.get(r.get("model") or "", r.get("model") or "—")
            cost = usage_stats.cost_for(r)
            for col, val in enumerate([ts, r.get("kind", ""), model,
                                       fmt(r.get("tokens_in", 0) or 0),
                                       fmt(r.get("tokens_out", 0) or 0),
                                       f"${cost:.4f}"]):
                table.setItem(i, col, QTableWidgetItem(str(val)))
        table.resizeColumnsToContents()
        layout.addWidget(table, stretch=1)

        footer = QLabel(
            "Rates: API-equivalent, Anthropic & OpenAI published pricing (June 2026). "
            "ChatGPT counts include Codex's agent overhead, so they read higher than Claude. "
            "Edit config.COST_TABLE if rates change."
        )
        footer.setStyleSheet("color:#777; font-size:9pt;")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)  # Close has RejectRole — single, correct wiring
        layout.addWidget(bb)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contoso KB Chatbot")
        self.resize(1100, 780)
        self.settings = settings_mod.load_settings()
        self._model_migrated = settings_mod.migrate_default_model(self.settings)
        if self._model_migrated:
            settings_mod.save_settings(self.settings)
        self._session_start_ts = datetime.now().isoformat()
        self.session = Session.new()
        self.worker: Optional[TurnWorker] = None
        self.ingest_worker: Optional[IngestWorker] = None
        self._retriever: Optional[Retriever] = None
        self._today_queries = 0
        self._today_tokens = 0
        self._attachments: list = []
        self._suppress_dropdown_notices = True   # silenced until first real user change
        self._learn_mode = False
        self._last_assistant_turn: Optional[Turn] = None
        self._build_ui()
        # Window shows immediately; models + LLM warm-up load in background
        self._set_chat_enabled(False)
        self._init_thinking = ThinkingIndicator()
        self.statusBar().addWidget(self._init_thinking)
        self._init_thinking.start(INIT_WORDS)
        self.input.setPlaceholderText("Getting ready — one moment…")
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
        tb.addSeparator()
        self._act_learn = QAction("Learn Mode", self)
        tb.addAction(self._act_learn)
        self._act_exit_learn = QAction("Exit Learn Mode", self)
        self._act_exit_learn.setVisible(False)
        tb.addAction(self._act_exit_learn)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Product:"))
        self.product_box = QComboBox()
        self.product_box.addItem("Any", "")
        for p in config.PRODUCTS:
            self.product_box.addItem(config.PRODUCT_DISPLAY.get(p, p), p)
        filter_row.addWidget(self.product_box)
        filter_row.addWidget(QLabel("AI Provider:"))
        self.provider_box = QComboBox()
        for pid, prov in config.PROVIDERS.items():
            self.provider_box.addItem(prov["display"], pid)
        pidx = self.provider_box.findData(self.settings.default_provider)
        if pidx >= 0:
            self.provider_box.setCurrentIndex(pidx)
        filter_row.addWidget(self.provider_box)

        filter_row.addWidget(QLabel("Model:"))
        self.model_box = QComboBox()
        self._populate_model_box(self.settings.default_provider, self.settings.default_model)
        filter_row.addWidget(self.model_box)
        filter_row.addStretch()
        outer.addLayout(filter_row)

        self.chat_view = QTextBrowser()
        self.chat_view.setFont(QFont("Consolas", 10))
        self.chat_view.setOpenExternalLinks(True)
        self.chat_view.setReadOnly(True)
        outer.addWidget(self.chat_view, stretch=1)

        self._thinking = ThinkingIndicator()
        outer.addWidget(self._thinking)

        self.progress = QProgressBar(); self.progress.setVisible(False)
        outer.addWidget(self.progress)

        # Learn Mode feedback bar — appears under answers while Learn Mode is on
        self._feedback_bar = QWidget()
        fb_layout = QHBoxLayout(self._feedback_bar)
        fb_layout.setContentsMargins(4, 4, 4, 4)
        self._btn_mark_correct = QPushButton("✓ Mark as Correct")
        self._btn_mark_correct.setStyleSheet("background:#e8f5e9; color:#2e7d32;")
        self._btn_correct_add = QPushButton("✎ Correct / Add to KB")
        self._btn_correct_add.setStyleSheet("background:#fff8e1; color:#f57f17;")
        fb_layout.addWidget(self._btn_mark_correct)
        fb_layout.addWidget(self._btn_correct_add)
        fb_layout.addStretch()
        self._feedback_bar.setVisible(False)
        outer.addWidget(self._feedback_bar)
        self._btn_mark_correct.clicked.connect(self._on_mark_correct)
        self._btn_correct_add.clicked.connect(self._on_open_correction_editor)

        # Inline correction editor — hidden panel
        self._correction_panel = self._build_correction_panel()
        self._correction_panel.setVisible(False)
        outer.addWidget(self._correction_panel)

        # Attachment bar — hidden until files are attached
        self._attach_bar = QWidget()
        attach_layout = QHBoxLayout(self._attach_bar)
        attach_layout.setContentsMargins(4, 2, 4, 2)
        attach_layout.setSpacing(6)
        self._attach_bar.setVisible(False)
        outer.addWidget(self._attach_bar)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask a question about the Contoso KB… (drag & drop files or Ctrl+V to attach)")
        self.input.returnPressed.connect(self._send)
        # Catch Ctrl+V on the input box itself — QLineEdit consumes Paste before
        # MainWindow.keyPressEvent would ever see it (the common typing-focus case)
        self.input.installEventFilter(self)
        self._clip_btn = QPushButton("📎")
        self._clip_btn.setFixedWidth(36)
        self._clip_btn.setToolTip("Attach file (image or text)")
        self._clip_btn.clicked.connect(self._open_file_picker)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input)
        input_row.addWidget(self._clip_btn)
        input_row.addWidget(self.send_btn)
        outer.addLayout(input_row)

        self.setAcceptDrops(True)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Log: {config.LOG_FILE}")

        self._act_reindex.triggered.connect(self._reindex)
        self._act_settings.triggered.connect(self._open_settings)
        self._act_clear.triggered.connect(self._clear_chat)
        self._act_stop.triggered.connect(self._stop)
        self._act_logs.triggered.connect(self._open_logs)
        self._act_learn.triggered.connect(self._enter_learn_mode)
        self._act_exit_learn.triggered.connect(self._exit_learn_mode)
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        self.model_box.currentIndexChanged.connect(self._on_model_changed)
        self._set_inputs_enabled(True)

    def _build_correction_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background:#fffde7; border:1px solid #f9a825; border-radius:4px;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QLabel("Correct or extend the answer below:"))
        self._correction_text = QPlainTextEdit()
        self._correction_text.setFixedHeight(120)
        layout.addWidget(self._correction_text)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Title:"))
        self._correction_title = QLineEdit()
        self._correction_title.setPlaceholderText("Short article title, e.g. How to reverse a posted deal")
        row1.addWidget(self._correction_title)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Product:"))
        self._correction_product = QComboBox()
        for p in config.PRODUCTS:
            self._correction_product.addItem(config.PRODUCT_DISPLAY.get(p, p), p)
        row2.addWidget(self._correction_product)
        row2.addWidget(QLabel("Topic:"))
        self._correction_topic = QLineEdit()
        self._correction_topic.setPlaceholderText("e.g. Dealing, Finance")
        row2.addWidget(self._correction_topic)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Source URL (optional):"))
        self._correction_url = QLineEdit()
        self._correction_url.setPlaceholderText("https://help.contoso.example/display/…")
        row3.addWidget(self._correction_url)
        layout.addLayout(row3)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save to KB")
        save_btn.setStyleSheet("background:#4caf50; color:white;")
        save_btn.clicked.connect(self._on_save_correction)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(lambda: self._correction_panel.setVisible(False))
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return panel

    # ── Learn Mode ────────────────────────────────────────────────────────────
    def _enter_learn_mode(self):
        from Dev.kb_chatbot.settings import check_learn_password
        pwd, ok = QInputDialog.getText(
            self, "Learn Mode", "Enter password:", QLineEdit.Password
        )
        if not ok:
            return
        if not check_learn_password(pwd, self.settings.learn_mode_hash):
            try:
                with open(config.USAGE_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"kind": "learn_mode_failed_auth",
                                        "ts": datetime.now().isoformat()}) + "\n")
            except Exception:
                log.exception("Failed to log learn-mode auth failure")
            QMessageBox.warning(self, "Access Denied", "Incorrect password.")
            return
        self._learn_mode = True
        self._act_learn.setVisible(False)
        self._act_exit_learn.setVisible(True)
        self._append("system",
                     "Learn Mode active. Feedback controls appear after each answer.",
                     "#f57f17", "SYSTEM:")
        # If there's already an answer on screen, allow feedback on it immediately
        if self._last_assistant_turn is not None and self._last_assistant_turn.kind == "answer":
            self._feedback_bar.setVisible(True)

    def _exit_learn_mode(self):
        self._learn_mode = False
        self._act_learn.setVisible(True)
        self._act_exit_learn.setVisible(False)
        self._feedback_bar.setVisible(False)
        self._correction_panel.setVisible(False)
        self._append("system", "Learn Mode exited.", "#1b5e20", "SYSTEM:")

    def _on_mark_correct(self):
        if self._last_assistant_turn is None:
            return
        from Dev.kb_chatbot.chat.learn_writer import write_learned_entry
        question = self._get_last_user_question()
        title = (question[:80] if question else
                 self._last_assistant_turn.content[:80])
        try:
            write_learned_entry(
                library_path=self.settings.library_path,
                product="other",
                topic="verified",
                title=f"Verified: {title}",
                body_md=self._last_assistant_turn.content,
                url="",
                original_question=question,
            )
        except Exception as exc:
            self._append("system", f"Save failed: {exc}", "#c62828", "ERROR:")
            return
        self._feedback_bar.setVisible(False)
        self._correction_panel.setVisible(False)
        self._append("system", "Marked as correct — saved to Learn KB. Run Reindex to make it searchable.",
                     "#1b5e20", "SYSTEM:")

    def _on_open_correction_editor(self):
        if self._last_assistant_turn is None:
            return
        self._correction_text.setPlainText(self._last_assistant_turn.content)
        self._correction_title.setText(self._get_last_user_question()[:80])
        self._correction_panel.setVisible(True)

    def _on_save_correction(self):
        from Dev.kb_chatbot.chat.learn_writer import write_learned_entry
        body = self._correction_text.toPlainText().strip()
        title = self._correction_title.text().strip()
        if not body:
            QMessageBox.warning(self, "Empty", "Please enter the corrected answer text.")
            return
        if not title:
            QMessageBox.warning(self, "Missing title", "Please enter a short title.")
            return
        try:
            write_learned_entry(
                library_path=self.settings.library_path,
                product=self._correction_product.currentData(),
                topic=self._correction_topic.text().strip() or "general",
                title=title,
                body_md=body,
                url=self._correction_url.text().strip(),
                original_question=self._get_last_user_question(),
            )
        except Exception as exc:
            self._append("system", f"Save failed: {exc}", "#c62828", "ERROR:")
            return
        self._correction_panel.setVisible(False)
        self._feedback_bar.setVisible(False)
        self._append("system", "Saved to Learn KB. Run Reindex to make it searchable.",
                     "#1b5e20", "SYSTEM:")

    def _get_last_user_question(self) -> str:
        for turn in reversed(self.session.turns):
            if turn.get("role") == "user":
                return turn.get("content", "")
        return ""

    def _start_init_worker(self):
        self._init_worker = InitWorker(self.settings)
        self._init_worker.ready.connect(self._on_init_ready)
        self._init_worker.status.connect(self._on_init_status)
        self._init_worker.failed.connect(self._on_init_failed)
        self._init_worker.start()

    @Slot(str)
    def _on_init_status(self, msg: str):
        if "warming up" in msg.lower():
            self._init_thinking.pin(msg.split("—", 1)[-1].strip().rstrip("…"))

    @Slot(object)
    def _on_init_ready(self, retriever):
        self._init_thinking.stop()
        self.statusBar().removeWidget(self._init_thinking)
        self.input.setPlaceholderText(
            "Ask a question about the Contoso KB… (drag & drop files or Ctrl+V to attach)")
        self._retriever = retriever
        self.send_btn.setText("Send")
        self._set_chat_enabled(True)
        self.statusBar().showMessage("Ready")
        self._append("system", "Ready. Type a question below.", "#1b5e20", "SYSTEM:")
        if self._model_migrated:
            self._append("system",
                "Default model upgraded to Sonnet for better accuracy — "
                "change it back anytime in the dropdown.", "#1b5e20", "SYSTEM:")
            self._model_migrated = False

    @Slot(str)
    def _on_init_failed(self, err):
        self._init_thinking.stop()
        self.statusBar().showMessage(f"Init failed: {err}")
        self._append("system", f"Initialisation failed: {err}", "#c62828", "ERROR:")
        # Repurpose Send as a retry button so the user isn't locked out forever
        self.send_btn.setText("Retry init")
        self.send_btn.setEnabled(True)

    def _set_chat_enabled(self, enabled: bool):
        self.input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)

    def _append(self, role: str, text: str, colour: str, tag: str):
        ts = datetime.now().strftime("%H:%M:%S")
        safe_text = html_module.escape(text)
        if role == "ai":
            # Convert [Title](url) markdown links to HTML hyperlinks
            safe_text = _LINK_RE.sub(r'<a href="\2">\1</a>', safe_text)
        safe_text = safe_text.replace("\n", "<br>")
        block = (
            f'<p style="margin:4px 0; font-family:Consolas,monospace; font-size:10pt;">'
            f'<span style="color:#555;">{ts}</span> '
            f'<b style="color:{colour};">{html_module.escape(tag)}</b> '
            f'<span style="color:{colour};">{safe_text}</span>'
            f'</p>'
        )
        self.chat_view.append(block)
        self.chat_view.ensureCursorVisible()

    def _populate_model_box(self, provider_id: str, select_model: str = ""):
        """Fill the model dropdown for a provider. Silent — blocks signals and
        sets the suppress flag so programmatic repopulation posts no notice."""
        self._suppress_dropdown_notices = True
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for label, ident in config.models_for(provider_id).items():
            self.model_box.addItem(label, ident)
        target = select_model or config.default_model_for(provider_id)
        idx = self.model_box.findData(target)
        self.model_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.model_box.blockSignals(False)
        self._suppress_dropdown_notices = False

    @Slot(int)
    def _on_provider_changed(self, _index: int):
        provider_id = self.provider_box.currentData()
        self._populate_model_box(provider_id)
        display = config.PROVIDERS[provider_id]["display"]
        self._append("system", f"⇄ Switched to {display} — model set to {self.model_box.currentText()}",
                     "#6a1b9a", "PROVIDER:")
        if provider_id == "openai" and not codex_login_ok():
            self._append("system",
                "Codex CLI is not ready. Install it and run `codex login`, then try again.",
                "#c62828", "ERROR:")

    @Slot(int)
    def _on_model_changed(self, _index: int):
        if self._suppress_dropdown_notices:
            return
        self._append("system", f"⇄ Model changed to {self.model_box.currentText()}",
                     "#6a1b9a", "PROVIDER:")

    def _send(self):
        if self._retriever is None:
            # Send doubles as "Retry init" after a failed initialisation
            if self.send_btn.text() == "Retry init":
                self.send_btn.setText("Send")
                self.send_btn.setEnabled(False)
                self._init_thinking.start(INIT_WORDS)
                self._start_init_worker()
            return
        msg = self.input.text().strip()
        if not msg or self.worker:
            return
        self.input.clear()
        self._set_inputs_enabled(False)
        self._append("user", msg, "#0d47a1", "YOU:")

        # Snapshot but don't clear yet — attachments are kept if the turn ends in
        # clarification/abstain so the user can answer without re-attaching
        attachments = list(self._attachments)
        if attachments:
            names = ", ".join(a.filename for a in attachments)
            self._append("system", f"Attached: {names}", "#555555", "FILES:")

        provider_id = self.provider_box.currentData()
        if provider_id == "openai" and not codex_login_ok():
            self._append("system",
                "Codex CLI is not ready. Install it and run `codex login`, then try again.",
                "#c62828", "ERROR:")
            self._set_inputs_enabled(True)
            return
        try:
            llm = build_provider(provider_id)
        except (ClaudeCodeNotFoundError, CodexNotFoundError) as exc:
            self._append("system", str(exc), "#c62828", "ERROR:")
            self._set_inputs_enabled(True)
            return

        deps = Deps(retriever=self._retriever, llm=llm, usage_logger=_append_usage,
                    attachments=attachments, rewriter=make_rewriter(provider_id))
        filters = Filters(product=self.product_box.currentData() or None)
        model = self.model_box.currentData()
        self.worker = TurnWorker(msg, self.session, filters, model, deps)
        self.worker.signals.finished.connect(self._on_turn_done)
        self.worker.signals.failed.connect(self._on_turn_failed)
        self.worker.signals.progress.connect(self._on_turn_progress)
        deps.on_progress = self.worker.signals.progress.emit
        self._thinking.start(THINKING_WORDS)
        self.worker.start()

    @Slot(str)
    def _on_turn_progress(self, stage: str):
        if stage == "rephrase":
            self._thinking.pin(REPHRASE_TEXT)

    @Slot(object)
    def _on_turn_done(self, turn):
        self._thinking.stop()
        colour = "#212121"; tag = "AI:"
        if turn.kind == "abstain":
            colour, tag = "#5d4037", "ABSTAIN:"
        elif turn.kind == "clarification":
            colour, tag = "#ef6c00", "CLARIFY:"
        self._append("ai", turn.content, colour, tag)
        if self._attachments:
            if turn.kind == "answer":
                self._attachments.clear()
                self._refresh_attach_bar()
            else:
                self._append("system", "Attachments kept — they'll be sent with your next message.",
                             "#555555", "FILES:")
        self._last_assistant_turn = turn
        if self._learn_mode and turn.kind == "answer":
            self._feedback_bar.setVisible(True)
            self._correction_panel.setVisible(False)
        else:
            self._feedback_bar.setVisible(False)
        self._today_queries += 1
        self._today_tokens += turn.tokens_in + turn.tokens_out
        self.statusBar().showMessage(
            f"Today: {self._today_queries} queries · {self._today_tokens} tokens · Log: {config.LOG_FILE}"
        )
        self.worker = None
        self._set_inputs_enabled(True)

    @Slot(str)
    def _on_turn_failed(self, err):
        self._thinking.stop()
        self._append("system", f"Error: {err}", "#c62828", "ERROR:")
        self.worker = None
        self._set_inputs_enabled(True)

    # ── Attachments ──────────────────────────────────────────────────────────
    def _open_file_picker(self):
        if len(self._attachments) >= _MAX_ATTACHMENTS:
            return
        exts = " ".join(f"*{e}" for e in sorted(_ALL_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach file", "", f"Supported files ({exts})"
        )
        for p in paths:
            self._add_attachment_path(Path(p))

    def _add_attachment_path(self, path: Path):
        from Dev.kb_chatbot.prompt import Attachment
        if len(self._attachments) >= _MAX_ATTACHMENTS:
            self._append("system", f"Maximum {_MAX_ATTACHMENTS} attachments per message.", "#c62828", "SYSTEM:")
            return
        ext = path.suffix.lower()
        if ext not in _ALL_EXTS:
            self._append("system", f"Unsupported file type: {ext or path.name}", "#c62828", "SYSTEM:")
            return
        try:
            data = path.read_bytes()
        except Exception as exc:
            self._append("system", f"Could not read {path.name}: {exc}", "#c62828", "SYSTEM:")
            return
        is_image = ext in _IMAGE_EXTS
        if is_image and len(data) > _MAX_IMAGE_BYTES:
            self._append("system", f"{path.name} exceeds 4 MB limit — not attached.", "#c62828", "SYSTEM:")
            return
        if not is_image and len(data) > _MAX_TEXT_BYTES:
            self._append("system", f"{path.name} exceeds 1 MB limit — not attached.", "#c62828", "SYSTEM:")
            return
        att = Attachment(filename=path.name,
                         media_type=_MEDIA_TYPES.get(ext, "text/plain"),
                         data=data, is_image=is_image)
        self._attachments.append(att)
        self._refresh_attach_bar()

    def _refresh_attach_bar(self):
        layout = self._attach_bar.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, att in enumerate(self._attachments):
            chip = QWidget()
            row = QHBoxLayout(chip)
            row.setContentsMargins(4, 2, 4, 2)
            row.setSpacing(3)
            lbl = QLabel(f"📎 {att.filename}")
            lbl.setStyleSheet("background:#e3f2fd; border-radius:4px; padding:2px 6px;")
            rm_btn = QPushButton("×")
            rm_btn.setFixedSize(20, 20)
            rm_btn.setStyleSheet("border:none; color:#555;")
            rm_btn.clicked.connect(lambda _=False, idx=i: self._remove_attachment(idx))
            row.addWidget(lbl)
            row.addWidget(rm_btn)
            layout.addWidget(chip)
        layout.addStretch()
        self._attach_bar.setVisible(bool(self._attachments))
        self._clip_btn.setEnabled(len(self._attachments) < _MAX_ATTACHMENTS)

    def _remove_attachment(self, idx: int):
        if 0 <= idx < len(self._attachments):
            self._attachments.pop(idx)
            self._refresh_attach_bar()

    # ── Drag and Drop ────────────────────────────────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self._add_attachment_path(Path(local))
        event.acceptProposedAction()

    # ── Clipboard paste (Ctrl+V) ─────────────────────────────────────────────
    def eventFilter(self, obj, event):
        # QLineEdit consumes Ctrl+V before MainWindow.keyPressEvent fires, so an
        # event filter on the input box is needed for the focused-while-typing case.
        if (obj is self.input and event.type() == QEvent.KeyPress
                and event.matches(QKeySequence.Paste)):
            if self._try_paste_clipboard_image():
                return True  # consumed — don't let QLineEdit also paste
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        # Fallback for paste when focus is elsewhere in the window
        if event.matches(QKeySequence.Paste) and self._try_paste_clipboard_image():
            return
        super().keyPressEvent(event)

    def _try_paste_clipboard_image(self) -> bool:
        """Attach the clipboard image if there is one. Returns True if attached."""
        mime = QApplication.clipboard().mimeData()
        if not mime.hasImage():
            return False
        img = QApplication.clipboard().image()
        if img.isNull():
            return False
        self._attach_clipboard_image(img)
        return True

    def _attach_clipboard_image(self, img):
        from Dev.kb_chatbot.prompt import Attachment
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        if len(self._attachments) >= _MAX_ATTACHMENTS:
            self._append("system", f"Maximum {_MAX_ATTACHMENTS} attachments per message.", "#c62828", "SYSTEM:")
            return
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.WriteOnly)
        img.save(buffer, "PNG")
        buffer.close()
        data = bytes(byte_array)
        if len(data) > _MAX_IMAGE_BYTES:
            self._append("system", "Pasted image exceeds 4 MB limit — not attached.", "#c62828", "SYSTEM:")
            return
        n = sum(1 for a in self._attachments if a.filename.startswith("clipboard"))
        att = Attachment(filename=f"clipboard_{n + 1}.png", media_type="image/png",
                         data=data, is_image=True)
        self._attachments.append(att)
        self._refresh_attach_bar()

    def _stop(self):
        if self.worker:
            self.worker.cancel()

    def _open_settings(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QDialog.Accepted:
            self.settings = dlg.values()
            settings_mod.save_settings(self.settings)
            self._append("system", "Settings saved.", "#1b5e20", "SYSTEM:")
            # The Settings dialog sets the DEFAULT for next launch; the live
            # AI Provider / Model dropdowns above are the active selection.
            # Say so explicitly so a default change isn't mistaken for a live switch.
            default_display = config.PROVIDERS.get(
                self.settings.default_provider, config.PROVIDERS["claude"])["display"]
            active_display = config.PROVIDERS.get(
                self.provider_box.currentData(), config.PROVIDERS["claude"])["display"]
            if (self.settings.default_provider != self.provider_box.currentData()
                    or self.settings.default_model != self.model_box.currentData()):
                self._append("system",
                    f"Saved default is {default_display} ({config.MODEL_DISPLAY.get(self.settings.default_model, self.settings.default_model)}), "
                    f"applied on next launch. This session is still using {active_display} "
                    f"({self.model_box.currentText()}) — change the AI Provider dropdown above to switch now.",
                    "#6a1b9a", "PROVIDER:")

    def _clear_chat(self):
        self.chat_view.clear()
        self.session = Session.new()
        self._last_assistant_turn = None
        self._feedback_bar.setVisible(False)
        self._correction_panel.setVisible(False)
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


def _preflight_provider(provider_id: str) -> Optional[str]:
    if provider_id == "openai":
        if codex_login_ok():
            return None
        return ("Codex CLI is required for ChatGPT.\n\n"
                "Install the Codex CLI and run `codex login`, then re-launch.")
    if shutil.which("claude"):
        return None
    return ("Claude Code is required.\n\n"
            "Install from https://claude.com/claude-code, run `claude login`, "
            "and re-launch this app.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Contoso KB Chatbot")
    saved = settings_mod.load_settings()
    err = _preflight_provider(saved.default_provider)
    if err:
        QMessageBox.critical(None, "AI provider not ready", err)
        sys.exit(1)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
