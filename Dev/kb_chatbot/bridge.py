"""Single QWebChannel bridge between the web UI (JS) and the Python engine.

One ChatBridge is registered on the channel as `bridge`. JS calls @Slot methods
(JSON in/out) and listens to Signals. A turn runs OFF the GUI thread by reusing
gui.TurnWorker; the result comes back on the answerReady signal.

Only PySide6.QtCore is imported here (light) so the bridge + its pure helpers are
unit-testable without a QApplication or QtWebEngine."""
from __future__ import annotations
import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from Dev.kb_chatbot import config


def webui_dir() -> Path:
    """Folder holding the bundled web UI (index.html, app.js, styles.css, vendor/)."""
    return Path(__file__).parent / "webui"


class ChatBridge(QObject):
    # Python -> JS
    answerReady = Signal(str)     # JSON: see _answer_payload
    turnFailed = Signal(str)
    turnProgress = Signal(str)

    def __init__(self, window=None) -> None:
        super().__init__()
        self._window = window
        self._worker = None

    # ── health / static data ────────────────────────────────────────────────
    @Slot(result=str)
    def ping(self) -> str:
        return "pong"

    @Slot(result=str)
    def providers(self) -> str:
        """The provider registry for the top-bar selector."""
        return json.dumps(config.PROVIDERS)

    # ── answer payload (pure; unit-tested) ───────────────────────────────────
    @staticmethod
    def _answer_payload(turn, context_chunks, chat_id: str = "") -> dict:
        sources = []
        for c in (context_chunks or []):
            m = getattr(c, "metadata", {}) or {}
            sources.append({
                "kind": m.get("kind", ""),
                "ticket_id": m.get("ticket_id", ""),
                "title": m.get("title", ""),
                "url": m.get("url", ""),
                "product": m.get("product", ""),
                "created_at": m.get("created_at", ""),
                "resolved": m.get("resolved", None),
            })
        return {
            "kind": turn.kind,
            "markdown": turn.content,
            "citations": list(turn.citations or []),
            "sources": sources,
            "debug": {
                "model": getattr(turn, "model", "") or "",
                "tokens_in": getattr(turn, "tokens_in", 0) or 0,
                "tokens_out": getattr(turn, "tokens_out", 0) or 0,
                "latency_ms": getattr(turn, "latency_ms", 0) or 0,
                "retrieved_ids": list(getattr(turn, "retrieved_ids", []) or []),
            },
            "chat_id": chat_id,
        }

    # ── send a turn (off-thread, reuses gui.TurnWorker) ──────────────────────
    @Slot(str, str)
    def send_message(self, text: str, product: str) -> None:
        w = self._window
        if w is None or getattr(w, "_retriever", None) is None:
            self.turnFailed.emit("Engine not ready yet.")
            return
        # Lazy imports avoid a circular import (gui imports bridge).
        from Dev.kb_chatbot.gui import TurnWorker
        from Dev.kb_chatbot.chat.orchestrator import Deps
        from Dev.kb_chatbot.retriever import Filters
        from Dev.kb_chatbot.llm import factory

        st = w.settings
        try:
            llm = factory.make_provider(st.default_provider, st)
        except Exception as exc:
            self.turnFailed.emit(f"Provider unavailable: {type(exc).__name__}")
            return
        deps = Deps(retriever=w._retriever, llm=llm,
                    answer_cache=getattr(w, "_answer_cache", None))
        worker = TurnWorker(text, w.session, Filters(product=(product or None)),
                            st.default_model, deps)
        worker.signals.finished.connect(self._on_done)
        worker.signals.failed.connect(self.turnFailed.emit)
        worker.signals.progress.connect(self.turnProgress.emit)
        self._worker = worker
        worker.start()

    def _on_done(self, turn) -> None:
        chunks = []
        w = self._window
        try:
            ids = list(getattr(w.session, "last_context_ids", []) or []) if w else []
            if w and getattr(w, "_retriever", None) is not None and ids:
                chunks = w._retriever.get_by_ids(ids)
        except Exception:
            chunks = []
        self.answerReady.emit(json.dumps(self._answer_payload(turn, chunks)))

    @Slot()
    def stop(self) -> None:
        if self._worker is not None:
            try:
                self._worker.cancel()
            except Exception:
                pass
