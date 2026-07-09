import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.onboarding import providers as OB


def test_claude_install_commands_use_winget_no_node():
    cmds = OB.install_commands("claude")
    flat = " ".join(" ".join(c) for c in cmds).lower()
    assert "anthropic.claudecode" in flat
    assert "npm" not in flat and "nodejs" not in flat


def test_codex_install_requires_node_and_npm_package():
    cmds = OB.install_commands("codex")
    flat = " ".join(" ".join(c) for c in cmds).lower()
    assert "openjs.nodejs" in flat
    assert "@openai/codex" in flat


def test_local_needs_no_install():
    assert OB.install_commands("local") == []


def test_login_commands():
    assert OB.login_command("claude") == ["claude", "auth", "login"]
    assert OB.login_command("codex") == ["codex", "login"]
    assert OB.login_command("local") is None


def test_check_claude_not_installed(monkeypatch):
    monkeypatch.setattr(OB.shutil, "which", lambda x: None)
    r = OB.check("claude")
    assert r.installed is False and r.ready is False and "install" in r.needs


def test_check_local_ready_when_creds_present(monkeypatch):
    class S:
        reasoning_base_url = "http://x:11500/v1"
        reasoning_username = "abdul"
    monkeypatch.setattr(OB.local_creds, "get_password", lambda u: "pw")
    r = OB.check("local", settings=S())
    assert r.ready is True


def test_check_local_not_ready_without_password(monkeypatch):
    class S:
        reasoning_base_url = "http://x:11500/v1"
        reasoning_username = "abdul"
    monkeypatch.setattr(OB.local_creds, "get_password", lambda u: None)
    r = OB.check("local", settings=S())
    assert r.ready is False and "credentials" in r.needs
