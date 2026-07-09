r"""Detect each reasoning provider's readiness and return the exact install/login
commands. Actions run in a VISIBLE console (the app hides normal subprocesses).

Confirmed 2026-07:
  Claude - native install (winget / PowerShell), no Node; login `claude auth login`;
           creds at %USERPROFILE%\.claude\.credentials.json; `claude.exe` on PATH.
  Codex  - Node.js 22+ then `npm install -g @openai/codex`; login `codex login`;
           detect via `codex login status` (exit 0); Windows `.CMD` shim.
  Local  - no install; needs gateway URL + username (settings) + password (keyring)."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from Dev.kb_chatbot.llm import local_creds


@dataclass
class Readiness:
    provider_id: str
    installed: bool = False
    logged_in: bool = False
    ready: bool = False
    needs: list[str] = field(default_factory=list)


def install_commands(provider_id: str) -> list[list[str]]:
    if provider_id == "claude":
        return [["winget", "install", "--id", "Anthropic.ClaudeCode", "-e",
                 "--accept-source-agreements", "--accept-package-agreements"]]
    if provider_id == "codex":
        return [["winget", "install", "--id", "OpenJS.NodeJS.LTS", "-e",
                 "--accept-source-agreements", "--accept-package-agreements"],
                ["npm", "install", "-g", "@openai/codex"]]
    return []


def login_command(provider_id: str) -> Optional[list[str]]:
    if provider_id == "claude":
        return ["claude", "auth", "login"]
    if provider_id == "codex":
        return ["codex", "login"]
    return None


def _claude_logged_in() -> bool:
    creds = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".claude" / ".credentials.json"
    if creds.exists() and creds.stat().st_size > 0:
        return True
    exe = shutil.which("claude")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "auth", "status"], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False


def _codex_logged_in() -> bool:
    exe = shutil.which("codex")
    if not exe:
        return False
    argv = ["cmd", "/c", exe, "login", "status"] if sys.platform == "win32" \
        and exe.lower().endswith((".cmd", ".bat")) else [exe, "login", "status"]
    try:
        return subprocess.run(argv, capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def check(provider_id: str, settings: Optional[object] = None) -> Readiness:
    r = Readiness(provider_id=provider_id)
    if provider_id == "local":
        url = getattr(settings, "reasoning_base_url", "") if settings else ""
        user = getattr(settings, "reasoning_username", "") if settings else ""
        has_pw = bool(local_creds.get_password(user)) if user else False
        r.installed = True  # nothing to install
        r.logged_in = bool(url and user and has_pw)
        r.ready = r.logged_in
        if not (url and user):
            r.needs.append("gateway-url-and-username")
        if not has_pw:
            r.needs.append("credentials")
        return r
    exe = "claude" if provider_id == "claude" else "codex"
    r.installed = shutil.which(exe) is not None
    if not r.installed:
        r.needs.append("install")
    r.logged_in = _claude_logged_in() if provider_id == "claude" else _codex_logged_in()
    if r.installed and not r.logged_in:
        r.needs.append("login")
    r.ready = r.installed and r.logged_in
    return r


def run_visible(argv: list[str]) -> None:
    """Launch a command in a NEW VISIBLE console (the app hides normal subprocesses,
    but install/login need to be user-visible + interactive)."""
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", "", *argv], close_fds=True)
    else:
        subprocess.Popen(argv)
