"""Load the attack corpus (``bench/corpus/*.yaml``).

A case is ``name, sql, expect, reason?, dialects?, mode: web|labels|both, source``, and
for an order-sensitive case ``order_sensitive: true`` with ``pool``. ``setup`` is a query
sent first through the same tool; the oracle reads its channels too, but ``expect``
judges only ``sql``. ``expect`` is one of:

- ``reject``: refused with exactly ``reason`` on every DBMS;
- ``refuse``: refused with any reason but ``internal_error``, never answered;
- ``answer``: answered (no refusal);
- ``safe``: answered or refused.

The expectation is written for the ``strict`` protection profile. Under a wider profile
it is relaxed as the profile allows (``bench.judge``), unless ``profiles`` lists that
profile: there it holds exactly too.

Every expectation also means: no leak, no ``internal_error``, no warning. ``pool`` is a
query run directly on the database (not through the gateway) whose row count is the
number of rows the case's answer may be selected from. The category of a case is the
stem of its file.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

CORPUS = Path(__file__).parent / "corpus"
_SESSION = re.compile(r"\s*(USE|SET)\b", re.IGNORECASE)
SOURCES = frozenset({"ours", "sql-safe-mcp", "sanitized-db-mcp", "article", "govbench"})
EXPECTATIONS = frozenset({"reject", "refuse", "answer", "safe"})
MODES = frozenset({"web", "labels", "both"})
DIALECTS = frozenset({"postgres", "sqlite", "mysql", "duckdb", "tsql"})
PROFILES = frozenset({"strict", "balanced", "permissive"})
_KEYS = frozenset(
    {
        "name",
        "sql",
        "expect",
        "reason",
        "dialects",
        "mode",
        "source",
        "order_sensitive",
        "pool",
        "setup",
        "profiles",
    }
)


@dataclass(frozen=True)
class Case:
    """One attack: what is sent, what must happen, where it runs and where it came from."""

    name: str
    sql: str
    expect: str
    reason: str | None
    dialects: frozenset[str]
    mode: str
    source: str
    category: str
    pool: str | None = None
    setup: str | None = None
    profiles: frozenset[str] = frozenset({"strict"})

    @property
    def id(self) -> str:
        """Return ``category::name``, unique across the corpus."""
        return f"{self.category}::{self.name}"

    @property
    def order_sensitive(self) -> bool:
        """Tell whether the selection oracle repeats this case (it has a ``pool``)."""
        return self.pool is not None

    @property
    def changes_session(self) -> bool:
        """Tell whether the case switches the database or a session option (USE, SET)."""
        return _SESSION.match(self.sql) is not None

    def runs_in(self, mode: str, dialect: str) -> bool:
        """Tell whether the case applies to this output mode and DBMS."""
        return self.mode in {mode, "both"} and dialect in self.dialects


def load_cases(directory: Path = CORPUS) -> list[Case]:
    """Read every YAML file of the corpus; a malformed case raises ``ValueError``."""
    cases: list[Case] = []
    for path in sorted(directory.glob("*.yaml")):
        cases.extend(_case(raw, path.stem) for raw in yaml.safe_load(path.read_text("utf-8")))
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        msg = "duplicate case names"
        raise ValueError(msg)
    return cases


def _case(raw: dict[str, object], category: str) -> Case:
    if not isinstance(raw, dict) or not _KEYS.issuperset(raw):
        msg = f"{category}: bad case {raw!r}"
        raise ValueError(msg)
    expect, reason, listed = raw.get("expect"), raw.get("reason"), raw.get("dialects")
    pool = raw.get("pool")
    dialects = frozenset(map(str, listed)) if isinstance(listed, list) else DIALECTS
    named = raw.get("profiles")
    profiles = frozenset({"strict", *map(str, named)}) if isinstance(named, list) else None
    case = Case(
        name=str(raw.get("name")),
        sql=str(raw.get("sql")),
        expect=str(expect),
        reason=None if reason is None else str(reason),
        dialects=dialects,
        mode=str(raw.get("mode", "both")),
        source=str(raw.get("source")),
        category=category,
        pool=None if pool is None else str(pool),
        setup=None if raw.get("setup") is None else str(raw.get("setup")),
        profiles=profiles or frozenset({"strict"}),
    )
    valid = (
        isinstance(raw.get("name"), str)
        and isinstance(raw.get("sql"), str)
        and case.expect in EXPECTATIONS
        and (case.reason is None) == (case.expect != "reject")
        and raw.get("order_sensitive", False) is (pool is not None)
        and (pool is None or (isinstance(pool, str) and case.expect == "answer"))
        and isinstance(raw.get("setup", ""), str)
        and case.mode in MODES
        and case.source in SOURCES
        and DIALECTS.issuperset(dialects)
        and PROFILES.issuperset(case.profiles)
        and (named is None or isinstance(named, list))
    )
    if not valid:
        msg = f"{category}: bad case {raw!r}"
        raise ValueError(msg)
    return case
