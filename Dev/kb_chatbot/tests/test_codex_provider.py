import base64
import json
from Dev.kb_chatbot.llm import codex_provider as cp


def test_codex_argv_wraps_windows_cmd_shim(monkeypatch):
    # npm installs codex as codex.CMD on Windows; CreateProcess can't launch a
    # .CMD directly, so it must be routed through `cmd /c`.
    monkeypatch.setattr(cp.sys, "platform", "win32")
    monkeypatch.setattr(cp.shutil, "which", lambda name: r"C:\npm\codex.CMD")
    argv = cp._codex_argv(["login", "status"])
    assert argv == ["cmd", "/c", r"C:\npm\codex.CMD", "login", "status"]


def test_codex_argv_plain_exe_not_wrapped(monkeypatch):
    monkeypatch.setattr(cp.sys, "platform", "linux")
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    argv = cp._codex_argv(["exec", "-"])
    assert argv == ["/usr/bin/codex", "exec", "-"]


def test_codex_argv_raises_when_missing(monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    try:
        cp._codex_argv(["exec"])
        assert False, "expected CodexNotFoundError"
    except cp.CodexNotFoundError:
        pass


def test_flatten_messages_includes_system_history_and_latest():
    msgs = [
        {"role": "user", "content": "How do I post a deal?"},
        {"role": "assistant", "content": "Which product?"},
        {"role": "user", "content": "CONTEXT…\nUSER QUESTION:\nTradeDesk"},
    ]
    out = cp._flatten_messages("SYSTEM RULES HERE", msgs)
    assert "SYSTEM RULES HERE" in out
    assert "How do I post a deal?" in out
    assert "Which product?" in out
    assert "TradeDesk" in out
    assert "USER:" in out and "ASSISTANT:" in out


def test_flatten_messages_extracts_text_from_multimodal():
    msgs = [{"role": "user", "content": [
        {"type": "image", "source": {}},
        {"type": "text", "text": "what is this error"},
    ]}]
    out = cp._flatten_messages("SYS", msgs)
    assert "what is this error" in out


def test_parse_usage_reads_turn_completed():
    stdout = "\n".join([
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 65608, "cached_input_tokens": 2432,
            "output_tokens": 19, "reasoning_output_tokens": 12}}),
    ])
    tin, tout = cp._parse_usage(stdout)
    assert tin == 65608
    assert tout == 31


def test_parse_usage_skips_non_json_lines():
    stdout = "ERROR some stderr-like noise\n" + json.dumps(
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
    tin, tout = cp._parse_usage(stdout)
    assert tin == 10 and tout == 5


def test_parse_usage_none_found():
    assert cp._parse_usage("not json at all\n{\"type\":\"turn.started\"}") == (0, 0)


def test_extract_agent_message():
    stdout = json.dumps({"type": "item.completed",
                         "item": {"type": "agent_message", "text": "pong"}})
    assert cp._extract_agent_message(stdout) == "pong"


def test_extract_image_files_writes_and_returns_paths():
    import os
    raw = b"\x89PNG\r\n"
    b64 = base64.b64encode(raw).decode()
    msgs = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
        {"type": "text", "text": "q"},
    ]}]
    paths = cp._extract_image_files(msgs)
    try:
        assert len(paths) == 1
        with open(paths[0], "rb") as fh:
            assert fh.read() == raw
    finally:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass


def test_chat_stubbed_subprocess(monkeypatch):
    class _Proc:
        stdout = json.dumps({"type": "turn.completed",
                             "usage": {"input_tokens": 100, "output_tokens": 20,
                                       "reasoning_output_tokens": 5}})
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kwargs):
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("Here is the answer.")
        return _Proc()

    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", fake_run)

    provider = cp.CodexProvider()
    resp = provider.chat(messages=[{"role": "user", "content": "hi"}],
                         model="gpt-5.4-mini", system_prompt="SYS")
    assert resp.text == "Here is the answer."
    assert resp.input_tokens == 100
    assert resp.output_tokens == 25
    assert resp.model == "gpt-5.4-mini"
    assert resp.cost_estimate_usd > 0


def test_ensure_codex_available_raises_when_missing(monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    try:
        cp._ensure_codex_available()
        assert False, "expected CodexNotFoundError"
    except cp.CodexNotFoundError:
        pass


def test_codex_login_ok_false_when_missing(monkeypatch):
    monkeypatch.setattr(cp, "_login_ok_cache", False)
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    assert cp.codex_login_ok() is False


def test_codex_login_ok_caches_success(monkeypatch):
    monkeypatch.setattr(cp, "_login_ok_cache", False)
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    calls = {"n": 0}

    class _Proc:
        returncode = 0

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        return _Proc()

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    assert cp.codex_login_ok() is True
    assert cp.codex_login_ok() is True   # second call served from cache
    assert calls["n"] == 1                # subprocess ran only once


def test_run_codex_exec_raises_on_nonzero_return(monkeypatch):
    class _Proc:
        stdout = ""
        stderr = "boom: codex blew up\nmore detail"
        returncode = 1
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", lambda *a, **k: _Proc())
    try:
        cp._run_codex_exec("prompt", "gpt-5.4-mini")
        assert False, "expected CodexExecError"
    except cp.CodexExecError as e:
        assert "boom" in str(e)


def test_run_codex_exec_raises_on_empty_output(monkeypatch):
    class _Proc:
        stdout = '{"type":"turn.started"}'
        stderr = ""
        returncode = 0
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", lambda *a, **k: _Proc())
    try:
        cp._run_codex_exec("prompt", "gpt-5.4-mini")
        assert False, "expected CodexExecError"
    except cp.CodexExecError:
        pass


def test_run_codex_exec_logs_stderr_not_prompt(monkeypatch, caplog):
    class _Proc:
        stdout = ""
        stderr = "stderr-secret-reason"
        returncode = 2
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", lambda *a, **k: _Proc())
    import logging as _l
    with caplog.at_level(_l.WARNING):
        try:
            cp._run_codex_exec("SENSITIVE-PROMPT-TEXT", "gpt-5.4-mini")
        except cp.CodexExecError:
            pass
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "stderr-secret-reason" in joined
    assert "SENSITIVE-PROMPT-TEXT" not in joined


def test_run_codex_exec_uses_utf8_encoding(monkeypatch):
    """The prompt must be sent as UTF-8, not the Windows locale codepage."""
    import json as _json
    captured = {}

    class _Proc:
        stdout = _json.dumps({"type": "turn.completed",
                              "usage": {"input_tokens": 1, "output_tokens": 1}})
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("ok")
        return _Proc()

    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", fake_run)

    cp._run_codex_exec("em—dash ✦ smart’quote prompt", "gpt-5.4-mini")
    assert captured.get("encoding") == "utf-8"
    assert captured.get("errors") == "replace"
    assert "text" not in captured  # must not rely on text=True (locale codepage)


def test_codex_login_ok_uses_utf8(monkeypatch):
    captured = {}

    class _Proc:
        returncode = 0

    monkeypatch.setattr(cp, "_login_ok_cache", False)
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run",
                        lambda cmd, **kw: (captured.update(kw), _Proc())[1])
    cp.codex_login_ok()
    assert captured.get("encoding") == "utf-8"
