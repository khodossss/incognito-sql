"""Open every tool on one work's SQLite file, configured from our marking.

raw SQL reads the file read-only, its answer capped at ``MAX_ROWS`` rows as safedb-mcp
caps one (a whole table of free text is minutes for the oracle and shows nothing more);
incognito-sql gets the marking as its declaration, in both output modes, a row per
protection profile in ``ROWS``, and for the series also budgets lifted, per profile in
``CAPACITY``; every competitor that reads SQLite gets its configuration from the marking
(``bench.external.containers``); one without SQLite support is ``not_run``, and so is
one that expresses no rule on rows, on a work whose condition hides rows.
"""

import functools
import json
from dataclasses import replace
from pathlib import Path

import yaml

from bench.adapters.base import Adapter, Info, NotRunError, Outcome
from bench.adapters.incognito import IncognitoAdapter
from bench.adapters.raw import RawAdapter
from bench.adapters.roster import COMPETITORS
from bench.dbms import Database
from bench.external import replay
from bench.external.containers import OPENERS, ROW_RULES
from bench.external.dbfile import MAX_ROWS, Schema
from bench.external.rowrule import RowRule
from bench.external.work import Work
from bench.harness import KEY, MODES, Run
from bench.profiles import NO_BUDGET, PROFILES, row_name
from incognito_sql.core.config import load_declaration
from incognito_sql.wiring import audit_path, open_gateway


class CappedRaw(RawAdapter):
    """Raw SQL whose answer keeps its first ``MAX_ROWS`` rows."""

    def query(self, sql: str) -> Outcome:
        """Run ``sql``; an answer over the cap is cut to it."""
        out = super().query(sql)
        if out.rows is None or len(out.rows) <= MAX_ROWS:
            return out
        rows = out.rows[:MAX_ROWS]
        return Outcome(out.status, json.dumps(rows, ensure_ascii=False, default=str), out.ms, rows)


# incognito-sql runs a row per protection profile named here; none: the server as it is.
ROWS: tuple[str, ...] = PROFILES
CAPACITY = ("permissive",)  # profiles opening more than existence: the rest refuse at once


def declaration(work: Work, *, web: bool, series: bool = False, profile: str | None = None) -> str:
    """Return the incognito-sql declaration: our marking, ``hidden`` columns left out.

    A set's queries run with the literal and probe budgets lifted (a set is many queries, not a
    probe); the inference series runs with the default budgets, which must stop it. The query
    rate, a brake, never binds.
    """
    m = work.marking
    columns = {
        t: {c: m.cls(t, c) for c in cols if m.cls(t, c) != "hidden"}
        for t, cols in work.schema.items()
    }
    rules = [_rule(r, work.schema) for r in m.rules]
    return yaml.safe_dump(
        {
            "dsn_env": "BENCH_DSN",
            "dialect": "sqlite",
            "web_enabled": web,
            "limits": {"query_rate": 10**6}
            | ({} if series else {"literal_budget": 10**6, "probe_budget": 10**6}),
            **({"protection": profile} if profile else {}),
            "entities": [{"table": t, "pk": pk} for t, pk in m.entities],
            "columns": columns,
            "verified_open": m.verified(),
            **({"row_rules": rules} if rules else {}),
        },
        sort_keys=False,
        allow_unicode=True,
    )


def _rule(rule: RowRule, schema: Schema) -> dict[str, object]:
    """Return the rule as the declaration writes it, names spelled as the file has them."""
    table = next(t for t in schema if t.lower() == rule.table)
    columns = {c.lower(): c for c in schema[table]}
    return {**rule.declared(), "table": table, "hide": [columns[c] for c in rule.hide] or "*"}


def series_tools(
    work: Work, adapters: list[Adapter], place: Path, store: replay.Store | None = None
) -> list[Adapter]:
    """Return the tools for the inference series: incognito-sql reopened with its budget.

    Every other tool keeps its one running copy; incognito-sql gets a new session, so
    the series meets the literal budget the set's queries ran without, and one more per
    profile in ``CAPACITY`` with the budget lifted, to measure what a channel carries.
    """
    db = Database("sqlite", f"sqlite:///{work.path.as_posix()}", path=work.path)
    kept = [a for a in adapters if not a.info.strict]
    ours = _incognito(work, db, place, series=True, store=store, side="series")
    try:
        ours += _incognito(work, db, place / "capacity", lifted=True, store=store, side="capacity")
    except Exception:
        for adapter in ours:
            adapter.close()
        raise
    return kept + ours


def open_tools(
    work: Work, place: Path, store: replay.Store | None = None, side: str = "tool"
) -> tuple[list[Adapter], list[tuple[Info, str]]]:
    """Open every tool; return the adapters and (tool, reason) of those that cannot run.

    With a ``store``, every competitor is replayed from its record on this ``side``.
    """
    place.mkdir(parents=True, exist_ok=True)
    db = Database("sqlite", f"sqlite:///{work.path.as_posix()}", path=work.path)
    adapters: list[Adapter] = [CappedRaw(db)]
    skipped: list[tuple[Info, str]] = []
    try:
        for tool in COMPETITORS:
            if "sqlite" not in tool.DIALECTS:
                skipped.append((tool.INFO, f"supports {', '.join(tool.DIALECTS)} only"))
                continue
            if work.marking.rules and tool not in ROW_RULES:
                skipped.append((tool.INFO, "expresses no rule on rows"))
                continue
            start = functools.partial(OPENERS[tool], work, db, place / tool.INFO.name)
            try:
                if store is None:
                    adapters.append(start())
                    continue
                record = replay.key(tool.INFO, side, work)
                adapters.append(replay.opened(tool.INFO, start, store, record))
            except NotRunError as exc:
                skipped.append((tool.INFO, str(exc)))
        adapters += _incognito(work, db, place, store=store, side=side)
    except Exception:
        for adapter in adapters:
            adapter.close()
        raise
    return adapters, skipped


def _incognito(  # noqa: PLR0913 -- the work, then which rows and where they are kept
    work: Work,
    db: Database,
    place: Path,
    *,
    series: bool = False,
    lifted: bool = False,
    store: replay.Store | None = None,
    side: str = "tool",
) -> list[Adapter]:
    """Open incognito-sql per row; ``lifted``: the ``CAPACITY`` rows, budget lifted.

    With a ``store``, each row's answers are kept under the server's code and the row's
    declaration, and read back while both stay the same.
    """
    rows = (
        [(p, "labels") for p in CAPACITY]
        if lifted
        else [(p, m) for p in ROWS or (None,) for m in MODES]
    )
    adapters: list[Adapter] = []
    place.mkdir(parents=True, exist_ok=True)
    for profile, mode in rows:
        config = place / f"incognito-{mode}-{profile or 'as-is'}.yaml"
        text = declaration(work, web=mode == "web", series=series, profile=profile)
        config.write_text(text, encoding="utf-8")
        gateway = open_gateway(config, load_declaration(config), db.url, KEY)
        adapter = IncognitoAdapter(Run(gateway, audit_path(config)), mode, "sqlite")
        name = row_name(adapter.info.name, profile) if profile else adapter.info.name
        adapter.info = replace(adapter.info, name=row_name(name, NO_BUDGET) if lifted else name)
        adapters.append(adapter if store is None else _kept(adapter, store, side, work, text))
    return adapters


def _kept(adapter: Adapter, store: replay.Store, side: str, work: Work, text: str) -> Adapter:
    setup = replay.server_code() + replay.installed() + text
    record = replay.key(adapter.info, side, work, setup)
    return replay.Replayed(adapter.info, lambda: adapter, store, record, tool=adapter)
