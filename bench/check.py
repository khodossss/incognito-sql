"""One corpus item end to end, shared by the SQLite gate and the five-DBMS matrix.

Besides the verdict on the answer, two checks read the database directly, never through
the gateway: a ``Watch`` (row counts of every table, or the bytes of a database file)
proves no write landed, and the selection oracle repeats an order-sensitive case and
compares it with its ``pool``.
"""

import json
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass

from bench.cases import Case
from bench.harness import Run, run_case
from bench.judge import Outcome, judge
from bench.templates import expand
from bench.world import World

Fetch = Callable[[str], list[tuple[object, ...]]]
SELECTION_RUNS = 20  # a constant pick among two equally likely rows: 2**-19


def state_sql(world: World) -> str:
    """Return one query counting the rows of every bench table."""
    counts = [f"(SELECT COUNT(*) FROM {t.name})" for t in world.stored]  # noqa: S608 -- own names
    return "SELECT " + ", ".join(counts)


def expected_state(world: World) -> tuple[int, ...]:
    """Return the row counts the world was built with."""
    return tuple(len(t.rows) for t in world.stored)


def counted(fetch: Fetch, world: World) -> tuple[int, ...]:
    """Return the current row counts, read directly from the database."""
    [row] = fetch(state_sql(world))
    return tuple(int(str(n)) for n in row)


def pool_sizes(cases: Iterable[Case], fetch: Fetch, dialect: str) -> dict[str, int]:
    """Count, directly on the database, the rows each order-sensitive case selects from."""
    return {c.id: len(fetch(c.pool)) for c in cases if c.pool is not None and dialect in c.dialects}


@dataclass(frozen=True)
class Watch:
    """A direct reading of the database (not through the gateway) and its value at build."""

    read: Callable[[], object]
    expected: object

    @classmethod
    def start(cls, read: Callable[[], object]) -> "Watch":
        """Take the first reading as the value every later one must equal."""
        return cls(read, read())


def check_case(  # noqa: PLR0913 -- the case, what it must not show, how it is watched
    run: Run,
    case: Case,
    forbidden: Iterable[str],
    stderr: Callable[[], str],
    watch: Watch,
    *,
    hidden_keys: Mapping[str, Collection[int]] | None = None,
) -> tuple[Outcome, list[str]]:
    """Run one case; return its outcome and every problem, including a write that landed."""
    outcome = run_case(run, case, stderr)
    problems = judge(case, outcome, forbidden, run.protection, hidden_keys)
    if (now := watch.read()) != watch.expected:
        problems.append(f"the database changed: {now} != {watch.expected}")
    return outcome, problems


def signature(answer: Mapping[str, object]) -> tuple[str, ...]:
    """Return the rows an answer selected, labels replaced by the entity keys behind them."""
    labels = answer.get("labels")
    keys = labels if isinstance(labels, dict) else {}
    rows = answer.get("rows")
    out = [
        json.dumps([keys.get(v, v) if isinstance(v, str) else v for v in row], sort_keys=True)
        for row in (rows if isinstance(rows, list) else [])
    ]
    return tuple(sorted(out))


def selection_problems(run: Run, case: Case, pool: int, runs: int = SELECTION_RUNS) -> list[str]:
    """Repeat the case; a selection that never changes while the pool offers more fails."""
    sql = expand(case.sql, run.tokens)

    def select() -> tuple[str, ...] | str:
        answer = run.gateway.query(sql, f"bench-select-{case.category}")
        return str(answer["error"]) if "error" in answer else signature(answer)

    first = select()
    if isinstance(first, str):
        return [f"order-sensitive case refused: {first}"]
    chosen = len(set(first))
    if chosen >= pool:
        return []  # every candidate was selected: there is no choice to vary
    if any(select() != first for _ in range(runs - 1)):
        return []
    return [f"selection constant over {runs} runs: {chosen} of {pool} candidates"]
