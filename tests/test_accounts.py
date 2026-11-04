"""Sign in: the accounts, the first password change, and the signed in user in the decision log."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from staffpilot import accounts, audit


def test_the_accounts_come_from_the_setting_or_the_defaults(monkeypatch):
    monkeypatch.delenv("STAFFPILOT_USERS", raising=False)
    assert accounts.configured() == {"admin": "admin", "kevin": "kevin", "khoa": "khoa", "hamad": "hamad"}
    # Semicolons work as separators too, and a pair without a name or a password is skipped.
    assert accounts.configured("a:a;b:secret, :x, c:, d") == {"a": "a", "b": "secret"}
    monkeypatch.setenv("STAFFPILOT_USERS", "ann:ann")
    assert accounts.configured() == {"ann": "ann"}


@pytest.mark.parametrize(
    ("value", "on"), [("", True), ("1", True), ("0", False), ("off", False), ("No", False)]
)
def test_sign_in_is_on_unless_turned_off(monkeypatch, value, on):
    monkeypatch.setenv("STAFFPILOT_LOGIN", value)
    assert accounts.enabled() is on


def test_a_first_password_must_be_changed_and_the_new_one_is_stored_hashed(tmp_path):
    book = accounts.Accounts(tmp_path, "kevin:kevin,ann:secret")
    assert book.check("kevin", "kevin") and book.check(" kevin ", "kevin")
    assert not book.check("kevin", "wrong") and not book.check("bob", "bob")
    assert book.must_change("kevin") and not book.must_change("ann") and not book.must_change(None)

    assert "1 to 6" in book.change("kevin", "", "")
    assert "1 to 6" in book.change("kevin", "toolong", "toolong")
    assert "user name" in book.change("kevin", "kevin", "kevin")
    assert "differ" in book.change("kevin", "abc", "abd")
    assert book.change("kevin", "abc", "abc") is None

    assert book.check("kevin", "abc") and not book.check("kevin", "kevin")
    assert not book.must_change("kevin")
    assert "current one" in book.change("kevin", "abc", "abc")
    stored = (tmp_path / accounts.FILE_NAME).read_text()
    assert "abc" not in stored and "hash" in stored
    # A second reader of the same folder, as after a restart, sees the new password.
    assert accounts.Accounts(tmp_path, "kevin:kevin").check("kevin", "abc")


def test_the_password_page_shows_until_the_first_password_is_changed(planner, tmp_path, monkeypatch):
    from staffpilot import app

    monkeypatch.setattr(app, "OUTPUTS", tmp_path)
    app.build_app(planner)
    request = SimpleNamespace(username="kevin")
    monkeypatch.setattr(app, "_ACCOUNTS", None)
    gate, sidebar, main, line, *_ = app.session_view(request)
    assert gate["visible"] is False and main["visible"] is True and line == ""

    monkeypatch.setattr(app, "_ACCOUNTS", accounts.Accounts(tmp_path, "kevin:kevin"))
    gate, sidebar, main, line, button, back, text = app.session_view(request)
    assert gate["visible"] is True and sidebar["visible"] is False and main["visible"] is False
    assert "Signed in as <b>kevin</b>" in line and "/logout" in line and "still your user name" in text
    assert button["visible"] is True and back["visible"] is False
    assert "1 to 6" in app.save_password("abcdefg", "abcdefg", request)[3]
    gate, sidebar, main, note, *_ = app.save_password("pw1", "pw1", request)
    assert gate["visible"] is False and main["visible"] is True and note == ""
    assert app.session_view(request)[0]["visible"] is False
    assert app.open_password(request)[5]["visible"] is True

    assert "Approved by kevin" in app.approve("Alpha", request=request)
    log = audit.read(tmp_path)
    assert set(log["user"]) == {"kevin"}


def test_the_sign_in_page_lists_the_users_and_offers_help():
    from staffpilot.ui import components

    message = components.login_message(["admin", "kevin"])
    assert "Users: admin, kevin." in message and "same as the user name" in message
    assert "Forgot password?" in message and "Please contact the Seven Team-5374." in message


def test_an_audit_file_written_before_the_user_column_still_lines_up(tmp_path):
    old = [c for c in audit.COLUMNS if c != "user"]
    pd.DataFrame([{c: "x" for c in old}]).to_csv(tmp_path / audit.FILE_NAME, index=False)
    assert list(audit.read(tmp_path).columns) == audit.COLUMNS
    audit.record([{"decision": "scenario run", "item": "demand"}], tmp_path, "khoa")
    frame = audit.read(tmp_path)
    assert list(frame.columns) == audit.COLUMNS and len(frame) == 2
    assert sorted(frame["user"]) == ["", "khoa"]
