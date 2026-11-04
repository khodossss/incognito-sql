import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from incognito_sql.core.budget import SESSIONLESS, LiteralBudget
from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.tokens.crypto import Cipher

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _lits(n: int, start: int = 0) -> list[str]:
    return [f"Zqname{i}" for i in range(start, start + n)]


def test_twenty_one_distinct_literals_rejected(budget: LiteralBudget) -> None:
    budget.spend("c1", _lits(20), NOW)
    with pytest.raises(Rejection) as exc:
        budget.spend("c1", _lits(1, 20), NOW)
    assert exc.value.reason is Reason.LITERAL_BUDGET


def test_repeated_and_canonically_equal_literals_do_not_count(budget: LiteralBudget) -> None:
    budget.spend("c1", _lits(20), NOW)
    budget.spend("c1", [*_lits(20), "  ZQNAME3 "], NOW)


def test_new_connection_does_not_reset_window(budget: LiteralBudget) -> None:
    budget.spend("c1", _lits(20), NOW)
    with pytest.raises(Rejection):
        budget.spend("c2", _lits(1, 20), NOW + timedelta(seconds=5))


def test_window_slides(budget: LiteralBudget) -> None:
    budget.spend("c1", _lits(20), NOW)
    budget.spend("c2", _lits(5, 100), NOW + timedelta(seconds=3601))


def test_rejected_spend_records_nothing(budget: LiteralBudget) -> None:
    budget.spend("c1", _lits(19), NOW)
    with pytest.raises(Rejection):
        budget.spend("c1", _lits(3, 19), NOW)
    budget.spend("c1", _lits(1, 19), NOW)  # the rejected ones left no trace


def test_alarm_active_then_expires(budget: LiteralBudget) -> None:
    assert not budget.alarm_active(NOW)
    budget.spend("c1", _lits(20), NOW)
    with pytest.raises(Rejection):
        budget.spend("c1", _lits(1, 20), NOW)
    assert budget.alarm_active(NOW + timedelta(seconds=3599))
    assert not budget.alarm_active(NOW + timedelta(seconds=3601))


def test_naive_datetime_rejected(budget: LiteralBudget) -> None:
    with pytest.raises(ValueError, match="timezone"):
        budget.spend("c1", ["x"], datetime(2026, 1, 1, 12, 0))  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone"):
        budget.alarm_active(datetime(2026, 1, 1, 12, 0))  # noqa: DTZ001


def test_no_plaintext_literal_in_db_files(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    b = LiteralBudget(path, Cipher(bytes(range(32))), Limits())
    b.spend("c1", ["Zqcanary Ivan"], NOW)
    blobs = [p.read_bytes() for p in tmp_path.glob("t.db*")]  # db, -wal, -shm
    assert any(blobs)
    assert not any(b"Zqcanary" in blob or b"zqcanary" in blob for blob in blobs)
    b.close()


def test_a_connection_cap_outlives_the_window(budget: LiteralBudget) -> None:
    budget.spend("c1", _lits(20), NOW)
    later = NOW + timedelta(seconds=3601)
    budget.spend("c2", _lits(1, 20), later)  # the installation window has slid
    with pytest.raises(Rejection):
        budget.spend("c1", _lits(1, 21), later)  # c1 has probed twenty for its whole life


def test_exact_literals_count_each_spelling(budget: LiteralBudget) -> None:
    budget.spend("c1", _lits(18), NOW, exact=["Zqname1", "Zqname1"])
    budget.spend("c1", [], NOW, exact=["zqname1"])
    with pytest.raises(Rejection):
        budget.spend("c1", [], NOW, exact=["ZQNAME1"])


def test_an_exact_literal_never_shares_a_unit_with_a_canonical_one(
    budget: LiteralBudget,
) -> None:
    budget.spend("c1", _lits(20), NOW)
    with pytest.raises(Rejection):
        budget.spend("c1", [], NOW, exact=["zqname0"])


def test_a_sessionless_spend_is_counted_by_the_window_only(budget: LiteralBudget) -> None:
    budget.spend(SESSIONLESS, _lits(20), NOW)
    with pytest.raises(Rejection):  # a burst is caught by the window
        budget.spend(SESSIONLESS, _lits(1, 20), NOW + timedelta(seconds=5))
    later = NOW + timedelta(seconds=3601)
    budget.spend(SESSIONLESS, _lits(20, 100), later)  # no count of its own after the window
    with pytest.raises(Rejection):
        budget.spend("c1", _lits(1, 200), later)  # the window is shared with sessions


def test_sessionless_spends_in_one_window_add_up(budget: LiteralBudget) -> None:
    budget.spend(SESSIONLESS, _lits(10), NOW)
    budget.spend(SESSIONLESS, _lits(10, 10), NOW + timedelta(seconds=5))
    with pytest.raises(Rejection):
        budget.spend(SESSIONLESS, _lits(1, 20), NOW + timedelta(seconds=10))


def test_sessionless_spends_past_the_window_are_dropped(
    budget: LiteralBudget, tmp_path: Path
) -> None:
    budget.spend(SESSIONLESS, _lits(10), NOW)
    budget.spend("c1", _lits(1, 50), NOW)
    budget.spend(SESSIONLESS, _lits(1, 10), NOW + timedelta(seconds=3601))
    with closing(sqlite3.connect(tmp_path / "t.db")) as con:
        rows = con.execute(
            "SELECT connection_id, COUNT(*) FROM budget_spend GROUP BY connection_id"
        ).fetchall()
    assert sorted(rows) == [(SESSIONLESS, 1), ("c1", 1)]


def test_probes_are_counted_by_the_window(tmp_path: Path) -> None:
    budget = LiteralBudget(tmp_path / "p.db", Cipher(bytes(range(32))), Limits(probe_budget=5))
    budget.spend("c1", [], NOW, probes=3)
    budget.spend("c1", [], NOW)  # a query without probes costs nothing
    with pytest.raises(Rejection) as exc:
        budget.spend("c2", ["Zqname"], NOW + timedelta(seconds=5), probes=3)
    assert exc.value.reason is Reason.PROBE_BUDGET
    assert budget.alarm_active(NOW + timedelta(seconds=5))
    budget.spend("c2", [], NOW + timedelta(seconds=6), probes=2)  # the refused three: uncounted
    budget.spend("c1", [], NOW + timedelta(seconds=3607), probes=5)  # the window has passed
    budget.close()


def test_a_literal_refusal_counts_no_probe(tmp_path: Path) -> None:
    budget = LiteralBudget(
        tmp_path / "p.db", Cipher(bytes(range(32))), Limits(literal_budget=1, probe_budget=2)
    )
    budget.spend("c1", ["Zqone"], NOW)
    with pytest.raises(Rejection) as exc:
        budget.spend("c1", ["Zqtwo"], NOW, probes=2)
    assert exc.value.reason is Reason.LITERAL_BUDGET
    budget.spend("c1", ["Zqone"], NOW, probes=2)  # the refused two probes were not counted
    budget.close()


def test_a_probe_refusal_spends_no_literal(tmp_path: Path) -> None:
    budget = LiteralBudget(
        tmp_path / "p.db", Cipher(bytes(range(32))), Limits(literal_budget=2, probe_budget=1)
    )
    budget.spend("c1", ["Zqa"], NOW, probes=1)
    with pytest.raises(Rejection) as exc:
        budget.spend("c1", ["Zqb"], NOW, probes=1)
    assert exc.value.reason is Reason.PROBE_BUDGET
    budget.spend("c1", ["Zqc"], NOW)  # Zqb was not spent: Zqa and Zqc fit in two
    budget.close()


def test_a_budget_of_zero_refuses_at_once_without_an_alarm(tmp_path: Path) -> None:
    limits = Limits(literal_budget=0, probe_budget=0)
    budget = LiteralBudget(tmp_path / "z.db", Cipher(bytes(range(32))), limits)
    for literals, exact, probes, reason in (
        (["Zqname"], (), 0, Reason.LITERALS_OFF),
        ([], ["M"], 0, Reason.LITERALS_OFF),
        ([], (), 1, Reason.PROBES_OFF),
    ):
        with pytest.raises(Rejection) as exc:
            budget.spend("c1", literals, NOW, exact=exact, probes=probes)
        assert exc.value.reason is reason
    budget.spend("c1", [], NOW)  # a query with neither passes
    assert not budget.alarm_active(NOW)
    budget.close()


def test_an_unlimited_budget_counts_nothing(tmp_path: Path) -> None:
    limits = Limits.model_validate({"literal_budget": "unlimited", "probe_budget": "unlimited"})
    budget = LiteralBudget(tmp_path / "u.db", Cipher(bytes(range(32))), limits)
    for i in range(50):
        budget.spend(f"c{i % 3}", _lits(5, 5 * i), NOW, exact=[f"Zq{i}"], probes=7)
    assert not budget.alarm_active(NOW)
    budget.close()
    with closing(sqlite3.connect(tmp_path / "u.db")) as con:
        spent = con.execute(
            "SELECT (SELECT COUNT(*) FROM budget_spend), (SELECT COUNT(*) FROM probe_spend)"
        )
        assert spent.fetchone() == (0, 0)


def test_spend_says_what_was_new_to_the_window(tmp_path: Path) -> None:
    budget = LiteralBudget(tmp_path / "s.db", Cipher(bytes(range(32))), Limits())
    first = budget.spend("c1", ["Zqone", "zqone "], NOW, exact=["M"], probes=2)
    assert (first.literals, first.probes) == (2, 2)  # one canonical form, one exact
    again = budget.spend("c2", ["Zqone", "Zqtwo"], NOW, probes=1)
    assert (again.literals, again.probes) == (1, 1)  # Zqone is already in the window
    assert budget.spend("c1", [], NOW).literals == 0
    budget.close()
