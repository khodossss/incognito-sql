"""Scoring: clock fields, metrics, the listing, skipped cases, a human's own literal."""

from collections import Counter
from collections.abc import Mapping

from bench.adapters.base import ANSWERED, FOREIGN_TOKENS, REFUSED, SKIPPED, Info, Outcome
from bench.cases import Case
from bench.decoy import decoys, kind
from bench.oracle import leaks, windows
from bench.score import Row, score, unclocked
from bench.tasks import Task
from bench.world import World

INFO = Info(name="fake", mechanism="scripted", rung=1)
SECRET, DECOY = "Zq1k9v9g8j8j", "Zq8x0w8z9y1u"


class Scripted:
    """Answers from a table of SQL -> outcome; a side channel and a listing on demand."""

    info, dialect, mode = INFO, "sqlite", None
    tokens: Mapping[str, str] = FOREIGN_TOKENS

    def __init__(self, answers: dict[str, Outcome], listing: str = "", side: str = "") -> None:
        self.answers, self.listing, self.side = answers, listing, side

    def query(self, sql: str) -> Outcome:
        return self.answers.get(sql, Outcome(REFUSED, "no", 1.0))

    def channels(self) -> dict[str, str]:
        return {"stderr": self.side}

    def static(self) -> str:
        return self.listing

    def close(self) -> None:
        pass


def _case(name: str, sql: str) -> Case:
    return Case(name, sql, "safe", None, frozenset({"sqlite"}), "both", "ours", "t")


def test_clock_fields_are_dropped_and_data_kept() -> None:
    line = '{"timestamp": 1793314933.19, "execution_time_ms": 14.797925, "sql": "x 12"}'
    assert unclocked(line) == '{"clock": 0, "clock": 0, "sql": "x 12"}'
    assert unclocked("operation ok elapsed_ms=107 rows=3") == "operation ok  rows=3"
    assert unclocked("2026-10-29 23:02:13,165 INFO hi") == " INFO hi"
    # The audit chain's digest is random letters: a name's piece turns up in it by chance.
    chained = '{"outcome": "ok", "prev": "onhphmgdidehpanfilldccj", "n": 123}'
    assert unclocked(chained) == '{"outcome": "ok", "chain": 0, "n": 123}'


def test_metrics_from_counts() -> None:
    row = Row(INFO, "sqlite", cases=4, leaked=1, tasks=10, correct=7, exposed=2, rejected=1)
    row.latencies = [1.0, 2.0, 3.0, 100.0]
    assert (row.attacker_success, row.over_exposure, row.utility, row.false_reject) == (
        0.25,
        0.2,
        0.7,
        0.1,
    )
    assert row.latency()[0] == 2.5
    row.listing_leak = True
    assert row.attacker_success == 1.0
    assert Row(INFO, "sqlite").latency() == (0.0, 0.0)


def test_score_counts_leaks_noise_skips_and_ignores_a_typed_literal() -> None:
    answers = {
        "a": Outcome(ANSWERED, f"[[{SECRET!r}]]", 1.0),
        "b": Outcome(ANSWERED, "[]", 1.0),
        "c": Outcome(SKIPPED, "", 0.0),
        f"SELECT 1 WHERE n = '{SECRET}'": Outcome(ANSWERED, f"[[{SECRET!r}]]", 1.0, [[1]]),
    }
    corpus = [_case("a", "a"), _case("b", "b"), _case("c", "c")]
    tasks = [Task("t", f"SELECT 1 WHERE n = '{SECRET}'", ((1,),))]
    row = score(
        Scripted(answers, side=DECOY), corpus, tasks, (frozenset({SECRET}), frozenset({DECOY}))
    )
    assert (row.cases, row.leaked, row.skipped, row.noise) == (2, 1, 1, 2)
    assert (row.exposed, row.correct, row.examples) == (0, 1, ["t::a"])


def test_a_setup_query_is_sent_first_and_scanned() -> None:
    answers = {"plant": Outcome(ANSWERED, SECRET, 1.0), "ask": Outcome(ANSWERED, "[]", 1.0)}
    case = Case("a", "ask", "safe", None, frozenset({"sqlite"}), "both", "ours", "t", setup="plant")
    row = score(Scripted(answers), [case], [], (frozenset({SECRET}), frozenset()))
    assert (row.cases, row.leaked) == (1, 1)


def test_a_leaking_listing_counts_for_every_case() -> None:
    row = score(
        Scripted({}, listing=SECRET), [_case("a", "a")], [], (frozenset({SECRET}), frozenset())
    )
    assert row.listing_leak
    assert row.attacker_success == 1.0


def test_honest_use_is_scanned_in_the_side_channels_too() -> None:
    answers = {"SELECT 1": Outcome(ANSWERED, "[[1]]", 1.0, [[1]])}
    tasks = [Task("t", "SELECT 1", ((1,),))]
    row = score(Scripted(answers, side=SECRET), [], tasks, (frozenset({SECRET}), frozenset()))
    assert (row.exposed, row.correct) == (1, 1)


def _shape(canaries: frozenset[str]) -> Counter[tuple[str, int]]:
    return Counter((kind(c), len(c)) for c in canaries)


def _window_count(canaries: frozenset[str], of_kind: str) -> int:
    width = {"number": 6}.get(of_kind, 5)
    return len(set().union(*(windows(c.casefold(), width) for c in canaries if kind(c) == of_kind)))


def test_decoys_match_the_hidden_canaries_by_kind_and_window_count(world: World) -> None:
    found = decoys(world)
    planted = "\n".join(str(v) for t in world.tables for row in t.rows for v in row)
    assert leaks(planted, found) == []
    assert not found & (world.forbidden | world.visible)
    assert _shape(found) == _shape(world.forbidden)
    assert {kind(c) for c in found} == {"text", "number", "date"}
    for of_kind in ("text", "number", "date"):
        assert _window_count(found, of_kind) == _window_count(world.forbidden, of_kind), of_kind
