"""Run the oracles on each identifier column against a gateway of its own.

The gateway is opened on a copy of the declaration in a temporary directory: its own
literal budget, journal and tokens, so the assessment never spends the budget live
agents share nor raises its alarm. Cuts and series ask it as one connection, as one
agent session would; a second pass with the literal budget lifted measures what each
channel carries.
"""

import json
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import yaml
from sqlalchemy.engine import Engine

from incognito_sql.assess.model import Assessment, ColumnLevels, HiddenColumn, Source, budgets_of
from incognito_sql.assess.truth import (
    DbTruth,
    hidden_columns,
    identifier_columns,
    targets,
    values,
)
from incognito_sql.core.config import load_declaration
from incognito_sql.core.config.model import column_operations, column_profile
from incognito_sql.core.config.protection import opens
from incognito_sql.core.db import make_engine
from incognito_sql.core.pipeline import Gateway
from incognito_sql.levels import asker as budgets
from incognito_sql.levels.asker import Ask, Asker, Reply
from incognito_sql.levels.cuts import cuts
from incognito_sql.levels.fragment import Fragments
from incognito_sql.levels.infer import CHANNELS
from incognito_sql.levels.oracle import Oracle
from incognito_sql.levels.partial import Visible, shown_in_part
from incognito_sql.levels.series import run_series
from incognito_sql.wiring import open_gateway

VALUES_CAP = 100_000  # distinct values of a column looked for in the answers
_LIFTED = 1_000_000


def assess(source: Source, *, count: int, capacity: bool) -> Assessment:
    """Assess every identifier column of an entity table on ``count`` targets each."""
    decl = source.decl
    engine = make_engine(
        source.dsn, decl.dialect, statement_timeout_ms=decl.limits.statement_timeout_ms
    )
    try:
        hidden = [HiddenColumn(t, c) for t, c in hidden_columns(engine, decl)]
        with _opened(source, lifted=False) as (gateway, connection):
            for closed in hidden:
                for _, sql in cuts(closed.table, closed.column, decl.dialect):
                    closed.cuts += 1
                    closed.refused += "error" in gateway.query(sql, connection)
        columns = list(identifier_columns(decl))
        held = [_column(source, engine, c, count, lifted=False) for c in columns]
        lifted = (
            [_column(source, engine, c, count, lifted=True) for c in columns] if capacity else []
        )
    finally:
        engine.dispose()
    return Assessment(held, lifted, hidden)


@contextmanager
def _opened(source: Source, *, lifted: bool) -> Iterator[tuple[Gateway, str]]:
    """Open a gateway on a copy of the config: its own budget, audit log and tokens."""
    with tempfile.TemporaryDirectory(prefix="incognito-assess-") as tmp:
        copy = _copy(source.config, Path(tmp), lifted=lifted)
        gateway = open_gateway(copy, load_declaration(copy), source.dsn, source.key)
        try:
            yield gateway, uuid.uuid4().hex
        finally:
            gateway.close()


def _column(
    source: Source, engine: Engine, column: tuple[str, str, str], count: int, *, lifted: bool
) -> ColumnLevels:
    """Assess one column against a gateway of its own: no column spends another's budget."""
    decl = source.decl
    table, name, key = column
    profile = column_profile(decl, table, name)
    leaks = opens(column_operations(decl, table, name))
    opened = frozenset(str(leak).removeprefix("L3 ") for leak in leaks)
    own = budgets_of(decl.limits)
    levels = ColumnLevels(table, name, profile, opened, measure=lifted, budgets=own)
    tool, series = (
        (budgets.CAPACITY_TOOL, budgets.CAPACITY_SERIES)
        if lifted
        else (budgets.TOOL_BUDGET, budgets.SERIES_BUDGET)
    )
    with _opened(source, lifted=lifted) as (gateway, connection):
        if not lifted:
            _cut(gateway, connection, values(engine, table, name, VALUES_CAP), levels, decl.dialect)
        asker = Asker(_asking(gateway, connection), tool, series, decl.dialect)
        for target in targets(engine, table, name, key, count):
            for channel in CHANNELS:
                levels.inference.add(run_series(asker, DbTruth(engine), target, channel))
    levels.inference.settle()
    return levels


def _cut(
    gateway: Gateway, connection: str, hidden: list[object], levels: ColumnLevels, dialect: str
) -> None:
    oracle, fragments = Oracle(hidden), Fragments(hidden)
    for _, sql in cuts(levels.table, levels.column, dialect):
        answer = gateway.query(sql, connection)
        levels.cuts += 1
        if "error" in answer:
            continue
        text = json.dumps(answer, ensure_ascii=False, default=str)
        whole = oracle.found(text)
        levels.whole += bool(whole)
        levels.parts += bool(shown_in_part(fragments.found(text), whole, (Visible([sql]),)))


def _asking(gateway: Gateway, connection: str) -> Ask:
    def ask(sql: str) -> Reply:
        answer, spend = gateway.ask(sql, connection)
        spent = (spend.literals, spend.probes)
        if "error" in answer:
            return Reply(answered=False, spend=spent)
        rows = answer.get("rows")
        text = json.dumps(answer, default=str)
        rows = rows if isinstance(rows, list) else None
        return Reply(answered=True, rows=rows, text=text, spend=spent)

    return ask


def _copy(config: Path, into: Path, *, lifted: bool) -> Path:
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    limits = data.setdefault("limits", {})
    limits["query_rate"] = _LIFTED  # a brake on a search, not a bound on what it learns
    if lifted:  # both: a budget left in place would cut the series and its cost short
        limits["literal_budget"] = limits["probe_budget"] = _LIFTED
    out = into / "assess.yaml"
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out
