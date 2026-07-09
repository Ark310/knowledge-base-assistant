import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import keyring
from keyring.backend import KeyringBackend
from Dev.kb_chatbot.llm import local_creds


class _MemKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self._d = {}

    def get_password(self, service, username):
        return self._d.get((service, username))

    def set_password(self, service, username, password):
        self._d[(service, username)] = password

    def delete_password(self, service, username):
        self._d.pop((service, username), None)


def _use_mem(monkeypatch):
    mem = _MemKeyring()
    monkeypatch.setattr(keyring, "get_password", mem.get_password)
    monkeypatch.setattr(keyring, "set_password", mem.set_password)
    monkeypatch.setattr(keyring, "delete_password", mem.delete_password)


def test_set_get_roundtrip(monkeypatch):
    _use_mem(monkeypatch)
    local_creds.set_password("abdul", "s3cret")
    assert local_creds.get_password("abdul") == "s3cret"


def test_get_missing_returns_none(monkeypatch):
    _use_mem(monkeypatch)
    assert local_creds.get_password("nobody") is None


def test_get_empty_username_returns_none(monkeypatch):
    _use_mem(monkeypatch)
    assert local_creds.get_password("") is None


def test_delete(monkeypatch):
    _use_mem(monkeypatch)
    local_creds.set_password("abdul", "x")
    local_creds.delete_password("abdul")
    assert local_creds.get_password("abdul") is None
