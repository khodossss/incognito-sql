"""The inference series (L3): targets, the attacker's questions, and judging the facts."""

from pathlib import Path

import pytest
from external_world import build

from bench.adapters.base import ERROR, REFUSED, SKIPPED, Outcome
from bench.adapters.raw import RawAdapter
from bench.dbms import Database
from bench.external import dbfile
from bench.external.asking import ask_of
from bench.external.marking import load
from bench.external.targets import SqliteTruth, targets
from incognito_sql.levels.asker import Asker, literal
from incognito_sql.levels.infer import CHANNELS, WHOLE, Inference, right
from incognito_sql.levels.series import Result, run_series
from incognito_sql.levels.target import Target, absent, forge


class Saying(RawAdapter):
    """Answers every query with one fixed outcome."""

    def __init__(self, db: Database, status: str, text: str = "", rows: object = None) -> None:
        super().__init__(db)
        self._out = Outcome(status, text, 0.0, rows)  # type: ignore[arg-type]

    def query(self, sql: str) -> Outcome:  # noqa: ARG002 -- one answer to every query
        return self._out


class UnderAggregates(RawAdapter):
    """Refuses every question but those on the column under ``max`` or ``min``."""

    def query(self, sql: str) -> Outcome:
        """Answer a question on an aggregate of the column; refuse the rest."""
        if "max(" in sql or "min(" in sql:
            return super().query(sql)
        return Outcome(REFUSED, "closed", 0.0, None)


@pytest.fixture
def shop(tmp_path: Path) -> tuple[Database, Path]:
    path, _ = build(tmp_path)
    return Database("sqlite", f"sqlite:///{path.as_posix()}", path=path), tmp_path


def _infer(adapter: RawAdapter, path: Path, count: int = 3) -> Inference:
    marking = load(path.parent / "shop.yaml")
    inference = Inference()
    asker = Asker(ask_of(adapter))
    with dbfile.opened(path) as con:
        for target in targets(con, marking, count):
            for channel in CHANNELS:
                inference.add(run_series(asker, SqliteTruth(con), target, channel))
    inference.settle()
    adapter.close()
    return inference


def test_targets_spread_over_hidden_columns_rows_by_a_unique_shown_key(
    shop: tuple[Database, Path],
) -> None:
    db, _ = shop
    assert db.path is not None
    marking = load(db.path.parent / "shop.yaml")
    with dbfile.opened(db.path) as con:
        chosen = targets(con, marking, 3)
    assert [(t.table, t.key, t.column) for t in chosen] == [
        ("orders", "id", "note"),
        ("people", "id", "email"),
        ("people", "id", "full_name"),
    ]


def test_forged_values_keep_their_form_and_miss_the_column(shop: tuple[Database, Path]) -> None:
    db, _ = shop
    assert db.path is not None
    forged = forge("Avel Quorin-7", "x")
    assert isinstance(forged, str)
    assert forged != "Avel Quorin-7"
    assert [c.isupper() for c in forged] == [c.isupper() for c in "Avel Quorin-7"]
    assert (forged[4], forged[11]) == (" ", "-")
    assert forged[12].isdigit()
    assert isinstance(forge(1234, "x"), int)
    assert isinstance(forge(12.5, "x"), float)
    target = Target("people", "id", 1, "full_name", "Avel Quorin")
    with dbfile.opened(db.path) as con:
        assert absent(SqliteTruth(con), target, "e") not in {None, "Avel Quorin"}
        assert absent(SqliteTruth(con), Target("people", "id", 1, "city", "----"), "e") is None


def test_raw_sql_gives_every_fact_and_reads_values_whole(shop: tuple[Database, Path]) -> None:
    db, _ = shop
    assert db.path is not None
    inference = _infer(RawAdapter(db), db.path)
    assert inference.whole == 2  # the 24-letter email outlasts 200 questions
    # a value recovered whole is L1 and counts in no channel: the email gives every fact
    assert {c: inference.inferred[c] for c in CHANNELS} == dict.fromkeys(CHANNELS, 1)
    assert inference.open_channels() == set(CHANNELS)
    assert inference.share("prefix") == "33% (1/3)"
    assert len(inference.costs[WHOLE]) == inference.whole
    # every form answers at once: one query per question, each a literal
    assert all(q == lit for c in inference.costs.values() for q, lit in c)
    assert inference.price("existence") == "2 / 2"


def test_a_fact_closed_in_one_form_is_read_in_another(shop: tuple[Database, Path]) -> None:
    db, _ = shop
    assert db.path is not None
    inference = _infer(UnderAggregates(db), db.path)
    assert inference.whole == 2  # the refused forms cost a query each, then max answers
    # the bare forms are refused once per series, then max answers first: queries > literals
    assert all(q > lit for c in inference.costs.values() for q, lit in c)
    assert inference.price("existence") == "-"
    assert inference.share("existence") == "0% (0/3)"  # asked of the whole column only
    assert {c: inference.inferred[c] for c in ("order", "length", "prefix", "contains")} == (
        dict.fromkeys(("order", "length", "prefix", "contains"), 1)
    )


@pytest.mark.parametrize(
    ("status", "text", "rows"),
    [(REFUSED, "no", None), (ERROR, "boom", None), ("answered", "n/a", [["x"]])],
)
def test_no_answer_teaches_nothing(
    shop: tuple[Database, Path], status: str, text: str, rows: object
) -> None:
    db, _ = shop
    assert db.path is not None
    inference = _infer(Saying(db, status, text, rows), db.path)
    assert not inference.open_channels()
    assert inference.whole == 0
    assert inference.costs == {}
    assert inference.share("order") == "0% (0/3)"


def test_a_channel_the_tool_cannot_express_is_skipped(shop: tuple[Database, Path]) -> None:
    db, _ = shop
    assert db.path is not None
    inference = _infer(Saying(db, SKIPPED), db.path)
    assert inference.share("length") == "skipped"
    assert Inference().share("length") == "-"


def test_the_asker_reads_counts_and_keeps_its_budgets(shop: tuple[Database, Path]) -> None:
    db, _ = shop
    tools = [Saying(db, "answered", t, r) for t, r in (("<td>2</td>", None), ("1 of 2", None))]
    tools += [Saying(db, "answered", "", r) for r in ([], [[0]])]
    asker = Asker(ask_of(tools[0]), budget=2)
    assert asker.ask("q") is True
    assert [Asker(ask_of(t)).ask("q") for t in tools[1:]] == [None, None, False]
    assert asker.ask("q") is True
    assert asker.ask("q") is None  # the tool's budget is spent
    tools.append(Saying(db, REFUSED))
    refused = Asker(ask_of(tools[-1]), budget=3)
    assert refused.ask_any(["a", "b", "c", "d"]) is None
    assert (refused.left, refused.skipped) == (0, False)  # a refused form costs a query
    tools.append(Saying(db, REFUSED))
    capped = Asker(ask_of(tools[-1]), budget=10, series_budget=2)
    assert capped.ask_any(["a", "b", "c"]) is None
    assert (capped.left, capped.spent) == (8, 2)  # the series' own budget stops it first
    for tool in tools:
        tool.close()
    assert [literal(v) for v in (3, 2.5, "O'Hara", True)] == ["3", "2.5", "'O''Hara'", "'True'"]


def test_a_claim_is_judged_against_the_target() -> None:
    target = Target("people", "id", 1, "full_name", "Avel Quorin")
    assert right(Result("prefix", target, claim="ave"))
    assert not right(Result("prefix", target, claim="av"))
    assert right(Result("contains", target, claim="quo"))
    assert not right(Result("contains", target, claim="zzz"))
    assert right(Result("length", target, claim="11"))
    assert not right(Result("existence", target))
    assert not right(Result("length", target))


def test_probes_right_by_chance_infer_nothing() -> None:
    target = Target("people", "id", 1, "full_name", "Avel Quorin")
    inference = Inference()
    inference.add(Result("order", target, probes=[(True, True), (False, False)]))
    inference.add(Result("order", target, probes=[(True, False), (False, True)]))
    inference.settle()
    assert inference.inferred["order"] == 0
    assert not inference.beyond_chance("order")


def test_a_refused_probe_is_no_answer_not_a_wrong_one() -> None:
    # the budget answers the first target of each database and refuses the next ones
    inference = Inference()
    for db in range(8):
        first = Target("people", "id", db, "full_name", f"Avel Quorin {db}")
        inference.add(Result("existence", first, probes=[(True, True), (False, False)]))
        for later in (1, 2):
            refused = Target("people", "id", db * 10 + later, "full_name", "Brisa Tolland")
            inference.add(Result("existence", refused, probes=[(True, None)]))
    inference.settle()
    assert inference.beyond_chance("existence")
    assert inference.inferred["existence"] == 8
    assert inference.share("existence") == "33% (8/24)"
