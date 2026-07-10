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


# config.PROVIDERS uses "openai"; the onboarding module speaks "codex" (Node CLI).
_ONBOARD_ID = {"openai": "codex"}


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
        self._workers = []        # keep running QThreads referenced so they aren't GC'd mid-run
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
        # Retain the thread until it truly finishes. cancel() only sets a flag checked
        # AFTER handle_turn returns, so a stopped/superseded worker (e.g. a hung local
        # call) keeps running up to the provider timeout. Overwriting self._worker would
        # drop the only reference and let Python GC a live QThread -> PySide crash
        # ("QThread: Destroyed while thread is still running"). Retire it on finish.
        self._workers.append(worker)
        worker.finished.connect(lambda w=worker: self._retire_worker(w))
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

    def _retire_worker(self, worker) -> None:
        """A worker's run() has returned — safe to drop the retain-reference + delete."""
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        if worker is self._worker:
            self._worker = None
        try:
            worker.deleteLater()
        except Exception:
            pass

    @Slot()
    def stop(self) -> None:
        self._turn_seq += 1   # invalidate the in-flight turn so its late result is ignored
        if self._worker is not None:
            try:
                self._worker.cancel()
            except Exception:
                pass
        self.turnStopped.emit()

    # ── settings (web modal) ─────────────────────────────────────────────────
    @Slot(result=str)
    def get_settings(self) -> str:
        """Settings for the web modal. SECURITY: never returns the gateway
        password — only whether one is stored (has_gateway_password)."""
        st = self._settings()
        user = (getattr(st, "reasoning_username", "") or "").strip()
        has_pw = False
        if user:
            try:
                from Dev.kb_chatbot.llm import local_creds
                has_pw = bool(local_creds.get_password(user))
            except Exception:
                has_pw = False
        return json.dumps({
            "library_path": str(getattr(st, "library_path", "")),
            "default_provider": getattr(st, "default_provider", config.DEFAULT_PROVIDER),
            "default_model": getattr(st, "default_model", config.DEFAULT_MODEL),
            "confidence_floor": float(getattr(st, "confidence_floor", config.CONFIDENCE_FLOOR)),
            "reasoning_base_url": getattr(st, "reasoning_base_url", "") or "",
            "reasoning_username": user,
            "has_gateway_password": has_pw,
        })

    @Slot(str, result=str)
    def save_settings(self, payload_json: str) -> str:
        try:
            data = json.loads(payload_json or "{}")
        except Exception:
            return json.dumps({"ok": False, "error": "bad payload"})
        st = self._settings()
        if data.get("library_path"):
            st.library_path = Path(str(data["library_path"]))
        if data.get("default_provider") in config.PROVIDERS:
            st.default_provider = data["default_provider"]
        if data.get("default_model"):
            st.default_model = data["default_model"]
            st.model_explicitly_set = True
        if "confidence_floor" in data:
            try:
                st.confidence_floor = float(data["confidence_floor"])
            except (TypeError, ValueError):
                pass
        if "reasoning_base_url" in data:
            st.reasoning_base_url = str(data.get("reasoning_base_url") or "").strip()
        if "reasoning_username" in data:
            st.reasoning_username = str(data.get("reasoning_username") or "").strip()
        # Keep provider/model consistent (mirror settings.load_settings guard).
        if config.provider_of_model(st.default_model) != st.default_provider:
            st.default_model = config.default_model_for(st.default_provider)
        self._save(st)
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def set_gateway_password(self, password: str) -> str:
        """Store the on-prem gateway password in the OS keyring only — never on
        disk, in settings.json, or in logs (org policy + local_creds contract)."""
        st = self._settings()
        user = (getattr(st, "reasoning_username", "") or "").strip()
        if not user:
            return json.dumps({"ok": False, "error": "Set the gateway username first."})
        if not password:
            return json.dumps({"ok": False, "error": "Password is empty."})
        try:
            from Dev.kb_chatbot.llm import local_creds
            local_creds.set_password(user, password)
        except Exception as exc:
            return json.dumps({"ok": False, "error": type(exc).__name__})
        return json.dumps({"ok": True})

    # ── onboarding wizard (Claude / Codex install+login, Local gateway) ───────
    @Slot(str, result=str)
    def onboarding_check(self, provider: str) -> str:
        from Dev.kb_chatbot.onboarding import providers as ob
        r = ob.check(_ONBOARD_ID.get(provider, provider), self._settings())
        return json.dumps({"provider": provider, "installed": r.installed,
                           "logged_in": r.logged_in, "ready": r.ready,
                           "needs": list(r.needs)})

    @Slot(str, result=str)
    def onboarding_install(self, provider: str) -> str:
        from Dev.kb_chatbot.onboarding import providers as ob
        cmds = ob.install_commands(_ONBOARD_ID.get(provider, provider))
        for argv in cmds:
            ob.run_visible(argv)
        return json.dumps({"ok": True, "launched": len(cmds)})

    @Slot(str, result=str)
    def onboarding_login(self, provider: str) -> str:
        from Dev.kb_chatbot.onboarding import providers as ob
        cmd = ob.login_command(_ONBOARD_ID.get(provider, provider))
        if not cmd:
            return json.dumps({"ok": False, "error": "This provider has no login step."})
        ob.run_visible(cmd)
        return json.dumps({"ok": True})

    # ── native Qt dialogs still owned by the window ──────────────────────────
    @Slot()
    def open_reindex(self) -> None:
        w = self._window
        if w is not None and hasattr(w, "_reindex"):
            try:
                w._reindex()
            except Exception:
                pass

    @Slot()
    def open_usage(self) -> None:
        w = self._window
        if w is None:
            return
        try:
            from Dev.kb_chatbot.gui import TokenUsageDialog
            TokenUsageDialog(w, getattr(w, "_session_start_ts", "")).exec()
        except Exception:
            pass

    # ── Learn Mode (password-gated KB contributions) ─────────────────────────
    @Slot(str, result=str)
    def learn_unlock(self, password: str) -> str:
        from Dev.kb_chatbot.settings import check_learn_password
        st = self._settings()
        ok = check_learn_password(password, getattr(st, "learn_mode_hash", "") or "")
        return json.dumps({"ok": bool(ok)})

    @Slot(str, result=str)
    def learn_submit(self, payload_json: str) -> str:
        try:
            data = json.loads(payload_json or "{}")
        except Exception:
            return json.dumps({"ok": False, "error": "bad payload"})
        body = (data.get("body_md") or "").strip()
        title = (data.get("title") or "").strip()
        if not title or not body:
            return json.dumps({"ok": False, "error": "Title and body are both required."})
        from Dev.kb_chatbot.chat.learn_writer import write_learned_entry
        st = self._settings()
        try:
            write_learned_entry(
                library_path=Path(str(getattr(st, "library_path", "."))),
                product=(data.get("product") or "other"),
                topic=(data.get("topic") or "verified"),
                title=title,
                body_md=body,
                url=(data.get("url") or ""),
                original_question=(data.get("original_question") or ""),
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": type(exc).__name__})
        return json.dumps({"ok": True})
