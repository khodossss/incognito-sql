"""Small guarantees: budget clock, one alarm row, bounded token issue, MAC key, private audit."""

import hashlib
import hmac
import itertools
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from incognito_sql.core.audit import AuditLog
from incognito_sql.core.budget import LiteralBudget
from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Rejection
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
KEY = bytes(range(32))


def _budget(path: Path) -> LiteralBudget:
    return LiteralBudget(path, Cipher(KEY), Limits(literal_budget=1, literal_window_s=3600))


def test_a_spend_never_moves_back_in_time(tmp_path: Path) -> None:
    budget = _budget(tmp_path / "t.db")
    budget.spend("c1", ["Zz a"], NOW)
    budget.spend("c1", ["Zz a"], NOW - timedelta(seconds=3000))  # a clock behind
    with pytest.raises(Rejection):  # "Zz a" still counts in the window
        budget.spend("c2", ["Zz b"], NOW + timedelta(seconds=700))
    budget.close()


def test_the_alarm_is_one_row(tmp_path: Path) -> None:
    budget = _budget(tmp_path / "t.db")
    budget.spend("c1", ["Zz a"], NOW)
    for i in range(3):
        with pytest.raises(Rejection):
            budget.spend("c1", [f"Zz other {i}"], NOW + timedelta(seconds=10 - i))
    con = sqlite3.connect(tmp_path / "t.db")
    try:
        assert con.execute("SELECT at FROM budget_alarm").fetchall() == [
            (int(NOW.timestamp()) + 10,)
        ]
    finally:
        con.close()
    assert budget.alarm_active(NOW + timedelta(seconds=3609))
    budget.close()


def test_token_issue_gives_up_after_repeated_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TokenStore(tmp_path / "d.db", Cipher(KEY), "inst:db", ttl_s=None)
    taken = store.tokenize("Zz one", NOW)
    calls = itertools.count(1)

    def always_taken() -> str:
        if next(calls) > 50:
            msg = "issue loops without a bound"
            raise AssertionError(msg)
        return taken

    monkeypatch.setattr("incognito_sql.core.tokens.store.new_token", always_taken)
    with pytest.raises(RuntimeError, match="token"):
        store.tokenize("Zz two", NOW)
    assert next(calls) == 9
    store.close()


def test_the_mac_key_is_not_the_value_key() -> None:
    assert Cipher(KEY).mac("Zz value") != hmac.new(KEY, b"Zz value", hashlib.sha256).digest()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_an_existing_audit_file_is_made_private(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)
    AuditLog(path)
    assert path.stat().st_mode & 0o777 == 0o600
