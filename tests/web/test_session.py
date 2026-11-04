"""One-time login codes and browser sessions, shared through the token-store file."""

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.web.session import CODE_TTL_S, SESSION_TTL_S, LoginRefused, Sessions

from .conftest import Clock, Parts


def test_a_code_is_exchanged_once(parts: Parts) -> None:
    sessions = parts.sessions
    code = sessions.issue_code()
    cookie = sessions.exchange(code)
    assert sessions.valid(cookie)
    with pytest.raises(LoginRefused):
        sessions.exchange(code)


@pytest.mark.parametrize("junk", ["", "zz-not-a-code", "tk_abcdefghijklmnop"])
def test_unknown_codes_and_cookies_are_refused(parts: Parts, junk: str) -> None:
    with pytest.raises(LoginRefused):
        parts.sessions.exchange(junk)
    assert not parts.sessions.valid(junk)


def test_lifetimes_are_five_minutes_and_seven_days(parts: Parts) -> None:
    assert (CODE_TTL_S, SESSION_TTL_S) == (300, 8 * 3600)
    sessions, clock = parts.sessions, parts.clock
    start = clock.now
    late, fresh = sessions.issue_code(), sessions.issue_code()
    clock.now = start + timedelta(seconds=CODE_TTL_S - 1)
    cookie = sessions.exchange(fresh)
    clock.now = start + timedelta(seconds=CODE_TTL_S)
    with pytest.raises(LoginRefused):
        sessions.exchange(late)
    signed_in = start + timedelta(seconds=CODE_TTL_S - 1)
    clock.now = signed_in + timedelta(seconds=SESSION_TTL_S - 1)
    assert sessions.valid(cookie)
    clock.now = signed_in + timedelta(seconds=SESSION_TTL_S)
    assert not sessions.valid(cookie)


def test_the_session_lifetime_is_the_configured_one(tmp_path: Path) -> None:
    clock = Clock()
    sessions = Sessions(
        tmp_path / "t.tokens.db", Cipher(bytes(range(32))), clock=clock, session_ttl_s=3600
    )
    try:
        cookie = sessions.exchange(sessions.issue_code())
        start = clock.now
        clock.now = start + timedelta(seconds=3599)
        assert sessions.valid(cookie)
        clock.now = start + timedelta(seconds=3600)
        assert not sessions.valid(cookie)
    finally:
        sessions.close()


def test_codes_and_cookies_are_random_and_long(parts: Parts) -> None:
    codes = {parts.sessions.issue_code() for _ in range(20)}
    assert len(codes) == 20
    cookies = {parts.sessions.exchange(c) for c in codes}
    assert len(cookies) == 20
    assert min(len(x) for x in codes | cookies) >= 43  # 256 bits, URL-safe base64


def test_another_process_exchanges_the_code(parts: Parts, tmp_path: Path) -> None:
    other = Sessions(tmp_path / "field.tokens.db", Cipher(bytes(range(32))), clock=Clock())
    try:
        cookie = other.exchange(parts.sessions.issue_code())
        assert parts.sessions.valid(cookie)
    finally:
        other.close()


def test_only_digests_reach_the_file(parts: Parts, tmp_path: Path) -> None:
    code = parts.sessions.issue_code()
    cookie = parts.sessions.exchange(parts.sessions.issue_code())
    con = sqlite3.connect(tmp_path / "field.tokens.db")
    try:
        rows = [
            *con.execute("SELECT * FROM web_login_code"),
            *con.execute("SELECT * FROM web_session"),
        ]
    finally:
        con.close()
    assert rows
    stored = repr(rows)
    files = b"".join(p.read_bytes() for p in tmp_path.glob("field.tokens.db*"))
    for secret in (code, cookie):
        assert secret not in stored
        assert secret.encode() not in files


def test_expired_digests_leave_the_file(parts: Parts, tmp_path: Path) -> None:
    sessions, clock = parts.sessions, parts.clock
    sessions.issue_code()  # never used
    sessions.exchange(sessions.issue_code())
    clock.now += timedelta(seconds=SESSION_TTL_S)
    sessions.issue_code()
    con = sqlite3.connect(tmp_path / "field.tokens.db")
    try:
        codes = con.execute("SELECT COUNT(*) FROM web_login_code").fetchone()[0]
        live = con.execute("SELECT COUNT(*) FROM web_session").fetchone()[0]
    finally:
        con.close()
    assert (codes, live) == (1, 0)
