"""Sign in for the app: who may open it, and the password change at the first sign in.

The accounts come from STAFFPILOT_USERS, written as `name:password` pairs separated by
commas, or from DEFAULT_USERS when it is unset. A password that equals its user name is
a first password: the app asks for a new one before it opens. New passwords are kept
salted and hashed in `outputs/accounts.json`, never as text; deleting that file brings
the first passwords back. STAFFPILOT_LOGIN=0 turns sign in off.

This is light sign in for a team: it records who approved each decision in the decision
log. It has no roles, and on a laptop the app is served over plain HTTP.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets


log = logging.getLogger(__name__)

DEFAULT_USERS = "admin:admin,kevin:kevin,khoa:khoa,hamad:hamad"
FILE_NAME = "accounts.json"
MIN_LENGTH, MAX_LENGTH = 1, 6
ROUNDS = 200_000


def enabled() -> bool:
    """Sign in is on unless STAFFPILOT_LOGIN is 0, false, no or off."""
    return os.environ.get("STAFFPILOT_LOGIN", "").strip().lower() not in {"0", "false", "no", "off"}


def configured(raw: str | None = None) -> dict[str, str]:
    """Names and first passwords from `raw`, STAFFPILOT_USERS or DEFAULT_USERS, in that order.

    Pairs may be separated by commas or semicolons; a pair without a name or a password is skipped.
    """
    text = raw if raw is not None else os.environ.get("STAFFPILOT_USERS", "").strip() or DEFAULT_USERS
    users = {}
    for pair in text.replace(";", ",").split(","):
        name, _, password = pair.strip().partition(":")
        if name.strip() and password:
            users[name.strip()] = password
    return users


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ROUNDS).hex()


class Accounts:
    """The users who may sign in, with the passwords they chose kept in `folder`."""

    def __init__(self, folder: Path, raw: str | None = None):
        self.path = Path(folder) / FILE_NAME
        self.users = configured(raw)

    @property
    def names(self) -> list[str]:
        return list(self.users)

    def _stored(self) -> dict[str, dict[str, str]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def check(self, name: str, password: str) -> bool:
        """True when `password` is the user's current password. Used by the sign in page."""
        name = (name or "").strip()
        if name not in self.users:
            return False
        saved = self._stored().get(name)
        if saved:
            return hmac.compare_digest(_hash(password, saved["salt"]), saved["hash"])
        return hmac.compare_digest(password.encode(), self.users[name].encode())

    def must_change(self, name: str | None) -> bool:
        """True while the user still has a first password equal to the user name."""
        return bool(name) and name in self.users and name not in self._stored() and self.users[name] == name

    def change(self, name: str, new: str, repeat: str) -> str | None:
        """Set a new password. Returns why it was refused, or None when it was saved."""
        if name not in self.users:
            return "Sign in again, then choose a new password."
        if not MIN_LENGTH <= len(new) <= MAX_LENGTH:
            return f"Use {MIN_LENGTH} to {MAX_LENGTH} characters."
        if new == name:
            return "Choose a password that differs from your user name."
        if self.check(name, new):
            return "Choose a password that differs from your current one."
        if new != repeat:
            return "The two passwords differ. Type the same one twice."
        stored = self._stored()
        salt = secrets.token_hex(16)
        stored[name] = {"salt": salt, "hash": _hash(new, salt)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(stored, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        log.info("Password changed for %s", name)
        return None
