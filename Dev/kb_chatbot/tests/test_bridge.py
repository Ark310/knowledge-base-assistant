import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.bridge import ChatBridge, webui_dir
from Dev.kb_chatbot.chat.session import Turn
from Dev.kb_chatbot.chunker import Chunk


def test_ping():
    assert ChatBridge().ping() == "pong"


def test_providers_json_has_local():
    d = json.loads(ChatBridge().providers())
    assert "local" in d and d["local"]["default_model"] == "contoso-reasoning-qwen25-7b"
    assert "claude" in d and "openai" in d


def test_answer_payload_shapes_turn():
    turn = Turn(role="assistant", kind="answer", content="Fixed it. [Ticket #1](u)",
                citations=[{"raw": "[Ticket #1](u)", "verified": True}],
                retrieved_ids=["ticket_1"], model="m", tokens_in=10, tokens_out=5,
                latency_ms=100)
    ctx = [Chunk(id="ticket_1", text="...", metadata={
        "kind": "ticket", "ticket_id": "1", "title": "Ticket #1", "url": "u",
        "product": "tradedesk", "created_at": "2024-01-01", "resolved": True})]
    p = ChatBridge._answer_payload(turn, ctx)
    assert p["kind"] == "answer"
    assert p["markdown"].startswith("Fixed it")
    assert p["citations"][0]["verified"] is True
    assert p["sources"][0]["ticket_id"] == "1" and p["sources"][0]["url"] == "u"
    assert p["sources"][0]["resolved"] is True
    assert p["debug"]["tokens_out"] == 5 and p["debug"]["model"] == "m"


def test_answer_payload_no_context():
    turn = Turn(role="assistant", kind="abstain", content="No info.", citations=[])
    p = ChatBridge._answer_payload(turn, [])
    assert p["kind"] == "abstain" and p["sources"] == []


def test_webui_dir_points_at_package_webui():
    d = webui_dir()
    assert d.name == "webui" and d.parent.name == "kb_chatbot"


def test_config_json_shape():
    import json as _j
    d = _j.loads(ChatBridge().config_json())
    assert d["default_provider"] in ("claude", "openai", "local")
    assert "formflow" in d["products"] and d["products"]["formflow"] == "FormFlow"
    assert "local" in d["provider_display"] and "local" in d["models_by_provider"]


# ── bug-169: hung-turn cancel + save-on-send + supersede guard ────────────────

def test_stop_bumps_seq_and_emits_turnstopped():
    b = ChatBridge()
    stopped = []
    b.turnStopped.connect(lambda: stopped.append(1))
    seq0 = b._turn_seq
    b.stop()  # no worker running -> just bump + signal, never wedged
    assert b._turn_seq == seq0 + 1
    assert stopped == [1]


def test_superseded_turn_result_is_dropped():
    # A late result from a stopped/superseded turn must not reach the UI.
    b = ChatBridge()
    failed = []
    b.turnFailed.connect(lambda m: failed.append(m))
    b._turn_seq = 5
    b._on_failed("late error from an abandoned turn", token=3)  # stale token
    assert failed == []
    b._on_failed("current error", token=5)                     # current token
    assert failed == ["current error"]


def test_retire_worker_drops_reference_so_live_qthread_not_gcd():
    # A stopped local call keeps running to timeout; we must retain then retire it,
    # never let self._worker reassignment GC a live QThread (PySide crash).
    b = ChatBridge()

    class FakeWorker:
        def __init__(self):
            self.deleted = False
        def deleteLater(self):
            self.deleted = True

    w = FakeWorker()
    b._workers.append(w)
    b._worker = w
    b._retire_worker(w)
    assert w not in b._workers
    assert b._worker is None
    assert w.deleted is True


# ── Task 6: settings / gateway creds / onboarding / learn bridge slots ────────

from Dev.kb_chatbot import settings as settings_mod
from Dev.kb_chatbot import config


class _FakeWindow:
    def __init__(self, st):
        self.settings = st
        self._session_start_ts = ""


def _settings_obj(**over):
    st = settings_mod.Settings(
        library_path=Path(str(over.get("library_path", "."))),
        default_model=over.get("default_model", config.DEFAULT_MODEL),
        confidence_floor=over.get("confidence_floor", config.CONFIDENCE_FLOOR),
    )
    st.default_provider = over.get("default_provider", "claude")
    st.reasoning_base_url = over.get("reasoning_base_url", "")
    st.reasoning_username = over.get("reasoning_username", "")
    return st


def test_get_settings_never_returns_the_gateway_password(monkeypatch):
    import Dev.kb_chatbot.llm.local_creds as lc
    monkeypatch.setattr(lc, "get_password", lambda u: "SUPERSECRET" if u else None)
    st = _settings_obj(reasoning_username="abdul", reasoning_base_url="http://ai-pc:11500/v1")
    d = json.loads(ChatBridge(_FakeWindow(st)).get_settings())
    assert d["reasoning_username"] == "abdul"
    assert d["has_gateway_password"] is True
    assert "password" not in d                       # no password field at all
    assert "SUPERSECRET" not in json.dumps(d)        # and the secret never leaks


def test_save_settings_updates_fields_and_keeps_model_consistent(monkeypatch):
    saved = {}
    monkeypatch.setattr(settings_mod, "save_settings", lambda s, *a, **k: saved.update({"s": s}))
    st = _settings_obj()
    r = json.loads(ChatBridge(_FakeWindow(st)).save_settings(json.dumps({
        "default_provider": "openai", "reasoning_base_url": "http://x:11500/v1",
        "reasoning_username": "abdul", "confidence_floor": 0.2})))
    assert r["ok"] is True
    assert st.default_provider == "openai"
    assert st.default_model == config.default_model_for("openai")  # consistency guard fired
    assert st.reasoning_username == "abdul"
    assert abs(st.confidence_floor - 0.2) < 1e-9
    assert saved.get("s") is st


def test_set_gateway_password_stores_in_keyring_only(monkeypatch):
    calls = {}
    import Dev.kb_chatbot.llm.local_creds as lc
    monkeypatch.setattr(lc, "set_password", lambda u, p: calls.update({"u": u, "p": p}))
    st = _settings_obj(reasoning_username="abdul")
    r = json.loads(ChatBridge(_FakeWindow(st)).set_gateway_password("hunter2"))
    assert r["ok"] is True and calls == {"u": "abdul", "p": "hunter2"}


def test_set_gateway_password_requires_a_username():
    st = _settings_obj(reasoning_username="")
    r = json.loads(ChatBridge(_FakeWindow(st)).set_gateway_password("hunter2"))
    assert r["ok"] is False and "username" in r["error"].lower()


def test_onboarding_check_maps_openai_to_codex(monkeypatch):
    from Dev.kb_chatbot.onboarding import providers as ob
    seen = {}

    class R:
        installed, logged_in, ready, needs = True, False, False, ["login"]

    monkeypatch.setattr(ob, "check", lambda pid, settings=None: (seen.update({"pid": pid}), R())[1])
    d = json.loads(ChatBridge(_FakeWindow(_settings_obj())).onboarding_check("openai"))
    assert seen["pid"] == "codex"                     # config "openai" -> onboarding "codex"
    assert d["provider"] == "openai" and d["installed"] is True and d["needs"] == ["login"]


def test_onboarding_install_launches_each_command(monkeypatch):
    from Dev.kb_chatbot.onboarding import providers as ob
    ran = []
    monkeypatch.setattr(ob, "install_commands", lambda pid: [["a"], ["b"]] if pid == "codex" else [])
    monkeypatch.setattr(ob, "run_visible", lambda argv: ran.append(argv))
    d = json.loads(ChatBridge(_FakeWindow(_settings_obj())).onboarding_install("openai"))
    assert d["ok"] is True and d["launched"] == 2 and ran == [["a"], ["b"]]


def test_onboarding_login_runs_the_login_command(monkeypatch):
    from Dev.kb_chatbot.onboarding import providers as ob
    ran = []
    monkeypatch.setattr(ob, "login_command", lambda pid: ["claude", "auth", "login"] if pid == "claude" else None)
    monkeypatch.setattr(ob, "run_visible", lambda argv: ran.append(argv))
    d = json.loads(ChatBridge(_FakeWindow(_settings_obj())).onboarding_login("claude"))
    assert d["ok"] is True and ran == [["claude", "auth", "login"]]


def test_learn_unlock_checks_the_password():
    b = ChatBridge(_FakeWindow(_settings_obj()))
    assert json.loads(b.learn_unlock("YOUR_LEARN_PASSWORD_HERE"))["ok"] is True   # default learn pw
    assert json.loads(b.learn_unlock("nope"))["ok"] is False


def test_learn_submit_writes_a_learned_entry(monkeypatch, tmp_path):
    import Dev.kb_chatbot.chat.learn_writer as lw
    got = {}
    monkeypatch.setattr(lw, "write_learned_entry",
                        lambda **kw: (got.update(kw), tmp_path / "x.json")[1])
    st = _settings_obj(library_path=str(tmp_path))
    r = json.loads(ChatBridge(_FakeWindow(st)).learn_submit(json.dumps({
        "title": "How to reverse a deal", "body_md": "Steps...",
        "product": "tradedesk", "topic": "Dealing"})))
    assert r["ok"] is True
    assert got["title"] == "How to reverse a deal" and got["product"] == "tradedesk"
    assert got["topic"] == "Dealing"


def test_learn_submit_requires_title_and_body():
    b = ChatBridge(_FakeWindow(_settings_obj()))
    assert json.loads(b.learn_submit(json.dumps({"title": "", "body_md": "B"})))["ok"] is False
