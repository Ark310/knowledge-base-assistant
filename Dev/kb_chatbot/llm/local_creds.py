"""Per-user gateway credentials in the OS keyring. The password is never written
to settings.json, logs, or anywhere on disk outside the keyring."""
from __future__ import annotations
from typing import Optional

import keyring

SERVICE = "contoso-kb-reasoning"


def set_password(username: str, password: str) -> None:
    keyring.set_password(SERVICE, username, password)


def get_password(username: str) -> Optional[str]:
    if not username:
        return None
    return keyring.get_password(SERVICE, username)


def delete_password(username: str) -> None:
    try:
        keyring.delete_password(SERVICE, username)
    except keyring.errors.PasswordDeleteError:
        pass
