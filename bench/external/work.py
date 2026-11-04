"""What runs on one database under one marking: honest tasks, attacks, and the oracle.

A base work holds the set's own questions on the database under our marking, and the
L2 cases cut from its hidden columns (``bench.external.cuts``); a condition work holds
the SecureSQL samples under one condition, with the columns it closes marked identifier
and the rows it hides under its rules: its attacks (DI, PR, RE) and its safe queries
(SA, SU) as honest tasks. Every honest task needs a reference answer computed on the file
directly, or on a copy with the rules applied; a query without one is left out and
counted.
"""

import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from bench.external import dbfile, lineage, rows
from bench.external.cuts import cuts
from bench.external.hidden import changes_nothing, hidden_columns, oracle_for, parts_for
from bench.external.marking import Marking
from bench.external.sets import Question, Record
from incognito_sql.levels.fragment import Fragments
from incognito_sql.levels.oracle import Oracle
from incognito_sql.levels.partial import Pieces


@dataclass(frozen=True)
class Task:
    """An honest question with its reference answer."""

    id: str
    source: str
    sql: str
    expect: tuple[tuple[object, ...], ...]
    opaque: frozenset[int]
    ordered: bool


@dataclass(frozen=True)
class Attack:
    """A SecureSQL attack sample: its queries are sent in turn through one tool."""

    id: str
    label: str
    queries: tuple[str, ...]


@dataclass
class Work:
    """One database file under one marking."""

    marking: Marking
    path: Path
    schema: dbfile.Schema
    oracle: Oracle
    parts: tuple[Fragments, Pieces]  # the L2 oracle and what is visible anyway
    tasks: list[Task] = field(default_factory=list)
    attacks: list[Attack] = field(default_factory=list)
    cuts: list[Attack] = field(default_factory=list)  # L2 cases, on the base work only
    left_out: Counter[tuple[str, str]] = field(default_factory=Counter)  # (set, why)


def works(
    path: Path, marking: Marking, questions: Sequence[Question], records: Sequence[Record]
) -> Iterator[Work]:
    """Yield the base work, then one work per condition that closes whole columns."""
    mine = [r for r in records if r.db == marking.db]
    known = {c.text for c in marking.conditions} | set(marking.rows_only)
    unknown = {r.condition for r in mine} - known
    if unknown:
        msg = f"{marking.db}: SecureSQL conditions not marked: {sorted(unknown)}"
        raise ValueError(msg)
    with dbfile.opened(path) as con:
        schema = dbfile.schema(con)
        missing = {pair for pair in marking.listed() if pair not in _pairs(schema)}
        if missing:
            msg = f"{marking.db}: marked columns not in the database: {sorted(missing)}"
            raise ValueError(msg)
        base = Work(
            marking, path, schema, oracle_for(con, marking, schema), parts_for(con, marking, schema)
        )
        hidden = hidden_columns(marking, schema)
        base.cuts = [Attack(name, "L2", (sql,)) for name, sql in cuts(schema, hidden)]
        for q in (q for q in questions if q.db == marking.db):
            _add_task(con, base, q.id, q.source, q.sql)
        yield base
        for condition in marking.conditions:
            under = marking.under(condition)
            same = not condition.rows and changes_nothing(con, schema, condition.columns)
            oracle = base.oracle if same else oracle_for(con, under, schema)
            parts = base.parts if same else parts_for(con, under, schema)
            work = Work(under, path, schema, oracle, parts)
            with ExitStack() as stack:
                answers = con if not condition.rows else stack.enter_context(_masked(path, under))
                for record in (r for r in mine if r.condition == condition.text):
                    if record.attack:
                        work.attacks.append(Attack(record.id, record.label, record.queries))
                        continue
                    for k, sql in enumerate(record.queries):
                        _add_task(answers, work, f"{record.id}.{k}", "securesql", sql)
            yield work


@contextmanager
def _masked(path: Path, marking: Marking) -> Iterator[sqlite3.Connection]:
    """Open a copy of the file with the marking's rules applied: as the gateway answers."""
    with tempfile.TemporaryDirectory(prefix="incognito-rows-", ignore_cleanup_errors=True) as tmp:
        copy = rows.masked_copy(path, Path(tmp) / path.name, marking.rules)
        with dbfile.opened(copy) as con:
            yield con


def _add_task(con: sqlite3.Connection, work: Work, task_id: str, kind: str, sql: str) -> None:
    hidden = hidden_columns(work.marking, work.schema)
    opaque, ordered = lineage.shape(sql, work.schema, hidden)
    expect = dbfile.reference(con, sql, ordered=ordered)
    if isinstance(expect, str):
        work.left_out[kind, expect] += 1
        return
    work.tasks.append(Task(task_id, kind, sql, tuple(expect), opaque, ordered))


def _pairs(schema: dbfile.Schema) -> set[tuple[str, str]]:
    return {(t.lower(), c.lower()) for t, cols in schema.items() for c in cols}
