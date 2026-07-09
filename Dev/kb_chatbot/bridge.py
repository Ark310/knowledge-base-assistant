"""Single QWebChannel bridge between the web UI (JS) and the Python engine.

One ChatBridge is registered on the channel as `bridge`. JS calls @Slot methods
(JSON in/out) and listens to Signals. A turn runs OFF the GUI thread by reusing
gui.TurnWorker; the result comes back on the answerReady signal. History is
persisted via chat.history. Only PySide6.QtCore is imported here (light) so the
bridge + its pure helpers are unit-testable without a QApplication."""
from __future__ import annotations
import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chat import history as _history


def webui_dir() -> Path:
    """Folder holding the bundled web UI (index.html, app.js, styles.css, vendor/)."""
    return Path(__file__).parent / "webui"


class ChatBridge(QObject):
    # Python -> JS
    answerReady = Signal(str)     # JSON payload (see _answer_payload)
    turnFailed = Signal(str)
    turnProgress = Signal(str)
    turnStopped = Signal()        # a turn was cancelled — re-enable the composer
    chatsChanged = Signal()       # ask JS to refresh the history list

    def __init__(self, window=None) -> None:
        super().__init__()
        self._window = window
        self._worker = None
        self._chat_id = None
        self._turn_seq = 0        # bumped to invalidate an in-flight turn's late result

    # ── settings access ──────────────────────────────────────────────────────
    def _settings(self):
        w = self._window
        if w is not None and getattr(w, "settings", None) is not None:
            return w.settings
        from Dev.kb_chatbot import settings as S
        return S.load_settings()

    def _save(self, st) -> None:
        try:
            from Dev.kb_chatbot import settings as S
            S.save_settings(st)
        except Exception:
            pass

    # ── health / static data ────────────────────────────────────────────────
    @Slot(result=str)
    def ping(self) -> str:
        return "pong"

    @Slot(result=str)
    def providers(self) -> str:
        return json.dumps(config.PROVIDERS)

    @Slot(result=str)
    def config_json(self) -> str:
        st = self._settings()
        return json.dumps({
            "default_provider": getattr(st, "default_provider", config.DEFAULT_PROVIDER),
            "default_model": getattr(st, "default_model", config.DEFAULT_MODEL),
            "products": config.PRODUCT_DISPLAY,
            "provider_display": {k: v["display"] for k, v in config.PROVIDERS.items()},
            "models_by_provider": {k: v["models"] for k, v in config.PROVIDERS.items()},
        })

    # ── provider / model selection ────────────────────────────────────────────
    @Slot(str)
    def set_provider(self, provider_id: str) -> None:
        st = self._settings()
        if provider_id in config.PROVIDERS:
            st.default_provider = provider_id
            st.default_model = config.default_model_for(provider_id)
            self._save(st)

    @Slot(str)
    def set_model(self, model_id: str) -> None:
        st = self._settings()
        st.default_model = model_id
        self._save(st)

    # ── chat history ──────────────────────────────────────────────────────────
    @Slot(result=str)
    def list_chats(self) -> str:
        return json.dumps(_history.list_chats())

    @Slot(str, result=str)
    def search_chats(self, query: str) -> str:
        return json.dumps(_history.search_chats(query))

    @Slot(str, result=str)
    def load_chat(self, chat_id: str) -> str:
        c = _history.load_chat(chat_id)
        if c and self._window is not None:
            from Dev.kb_chatbot.chat.session import Session
            s = Session.new()
            s.turns = c.get("turns", []) or []
            self._window.session = s
            self._chat_id = chat_id
            self._reset_conversation()
        return json.dumps(c or {})

    @Slot()
    def new_chat(self) -> None:
        self._turn_seq += 1   # drop any in-flight turn's late result
        if self._worker is not None:
            try:
                self._worker.cancel()
            except Exception:
                pass
        if self._window is not None:
            from Dev.kb_chatbot.chat.session import Session
            self._window.session = Session.new()
        self._chat_id = None
        self._reset_conversation()

    @Slot(str, str)
    def rename_chat(self, chat_id: str, title: str) -> None:
        _history.rename_chat(chat_id, title)
        self.chatsChanged.emit()

    @Slot(str)
    def delete_chat(self, chat_id: str) -> None:
        _history.delete_chat(chat_id)
        if chat_id == self._chat_id:
            self.new_chat()
        self.chatsChanged.emit()

    def _reset_conversation(self) -> None:
        # A loaded/new chat must not carry a persistent Claude conversation.
        import sys
        m = sys.modules.get("Dev.kb_chatbot.llm.claude_code_provider")
        if m is not None:
            try:
                m.ClaudeCodeProvider.reset_conversation()
            except Exception:
                pass

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
            self.turnFailed.emit("The knowledge base is still loading. Try again in a moment.")
            return
        from Dev.kb_chatbot.gui import TurnWorker
        from Dev.kb_chatbot.chat.orchestrator import Deps
        from Dev.kb_chatbot.retriever import Filters
        from Dev.kb_chatbot.llm import factory

        st = self._settings()
        try:
            llm = factory.make_provider(st.default_provider, st)
        except Exception as exc:
            self.turnFailed.emit(f"That provider isn't ready: {type(exc).__name__}. "
                                 f"Set its login/credentials in Settings.")
            return

        # Persist the chat immediately (with the pending question) so it shows in
        # history + is referable even if the model never answers or is stopped.
        try:
            snapshot = list(getattr(w.session, "turns", []) or []) + \
                [{"role": "user", "content": text, "kind": "user"}]
            self._chat_id = _history.save_chat(snapshot, self._chat_id)
            self.chatsChanged.emit()
        except Exception:
            pass

        self._turn_seq += 1
        token = self._turn_seq
        deps = Deps(retriever=w._retriever, llm=llm,
                    answer_cache=getattr(w, "_answer_cache", None))
        worker = TurnWorker(text, w.session, Filters(product=(product or None)),
                            st.default_model, deps)
        worker.signals.finished.connect(lambda turn, tok=token: self._on_done(turn, tok))
        worker.signals.failed.connect(lambda msg, tok=token: self._on_failed(msg, tok))
        worker.signals.progress.connect(self.turnProgress.emit)
        self._worker = worker
        worker.start()

    def _on_done(self, turn, token: int) -> None:
        if token != self._turn_seq:
            return  # a stopped / superseded turn — drop its late result
        chunks = []
        w = self._window
        try:
            ids = list(getattr(w.session, "last_context_ids", []) or []) if w else []
            if w and getattr(w, "_retriever", None) is not None and ids:
                chunks = w._retriever.get_by_ids(ids)
        except Exception:
            chunks = []
        try:
            if w is not None:
                turns = list(getattr(w.session, "turns", []) or [])
                self._chat_id = _history.save_chat(turns, self._chat_id)
        except Exception:
            pass
        self.answerReady.emit(json.dumps(self._answer_payload(turn, chunks, self._chat_id or "")))
        self.chatsChanged.emit()

    def _on_failed(self, msg: str, token: int) -> None:
        if token != self._turn_seq:
            return  # stopped / superseded
        self.turnFailed.emit(msg)

    @Slot()
    def stop(self) -> None:
        self._turn_seq += 1   # invalidate the in-flight turn so its late result is ignored
        if self._worker is not None:
            try:
                self._worker.cancel()
            except Exception:
                pass
        self.turnStopped.emit()
