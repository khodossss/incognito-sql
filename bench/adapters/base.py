"""The adapter shape: send one SQL query, get an outcome; drain the side channels.

Every tool is driven the same way. ``query`` returns what the model would read as the
answer; ``channels`` returns text that appeared elsewhere since the last call (stderr,
an audit log); ``static`` is the text the model reads once at connect (tool names,
descriptions, input schemas, instructions).
"""

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from bench.templates import spelling_fills, token_fills

ANSWERED, REFUSED, ERROR, SKIPPED = "answered", "refused", "error", "skipped"
Rows = list[list[object]]
# Corpus token templates for tools without our tokens: a token-shaped literal and its forms,
# and spellings of a value no table holds.
FOREIGN_TOKENS = token_fills("tk_" + "a" * 16) | spelling_fills("Zz Nobody Here")


@dataclass(frozen=True)
class Outcome:
    """One query's result and how long it took.

    ``status`` is ``answered``, ``refused`` (the tool said no), ``error`` (transport or tool
    failure) or ``skipped`` (the tool cannot express the query).
    """

    status: str
    text: str
    ms: float
    rows: Rows | None = None
    spend: tuple[int, int] | None = None  # literals and probes the tool's budgets counted


@dataclass(frozen=True)
class Info:
    """Who the tool is: row label, mechanism (for the ladder) and provenance."""

    name: str
    mechanism: str
    rung: int  # place on the ladder of defenses: 0 is no protection
    version: str = ""
    source: str = ""
    license: str = ""
    install: str = ""
    command: str = ""
    tool: str = ""  # the MCP tool that takes the SQL
    arguments: str = ""  # its arguments, as the report shows them
    strict: bool = False  # one hidden-canary window is a leak, whatever the decoys show


class Adapter(Protocol):
    """A tool opened against the world on one DBMS."""

    @property
    def info(self) -> Info:
        """Who the tool is."""
        ...

    @property
    def dialect(self) -> str:
        """The DBMS the tool is opened on."""
        ...

    @property
    def mode(self) -> str | None:
        """An output mode of ours; None: the tool has one, and every case runs once."""
        ...

    @property
    def tokens(self) -> Mapping[str, str]:
        """Fills of the corpus token templates for this tool."""
        ...

    def query(self, sql: str) -> Outcome:
        """Send one query."""
        ...

    def channels(self) -> dict[str, str]:
        """Return the side-channel text written since the last call."""
        ...

    def static(self) -> str:
        """Return the text the model reads once at connect."""
        ...

    def close(self) -> None:
        """Release the tool and its process."""
        ...


class NotRunError(Exception):
    """The tool cannot be run against this world here; the message is the fixed reason."""


class Tail:
    """A file another process appends to; ``read`` returns what is new since the last call."""

    def __init__(self, path: Path) -> None:
        """Follow ``path`` from its start."""
        self.path = path
        self._seen = 0

    def read(self) -> str:
        """Return the bytes appended since the last call, as text."""
        if not self.path.exists():
            return ""
        data = self.path.read_bytes()[self._seen :]
        self._seen += len(data)
        return data.decode("utf-8", errors="replace")


def timed(call: Callable[[], tuple[str, str, Rows | None]]) -> Outcome:
    """Run ``call`` and time it; an exception becomes an ``error`` outcome."""
    start = time.perf_counter()
    try:
        status, text, rows = call()
    except Exception as exc:  # noqa: BLE001 -- any failure of the tool is an outcome
        status, text, rows = ERROR, f"{type(exc).__name__}: {exc}", None
    return Outcome(status, text, (time.perf_counter() - start) * 1000, rows)


def dict_rows(records: object) -> Rows | None:
    """Turn a JSON list of row objects into rows, in key order."""
    if not isinstance(records, list):
        return None
    return [list(r.values()) if isinstance(r, dict) else [r] for r in records]


def as_json(value: object) -> str:
    """Serialise an answer the way it would reach the model."""
    return json.dumps(value, ensure_ascii=False, default=_plain)


def _plain(value: object) -> object:
    if isinstance(value, Decimal):
        try:
            return float(value)
        except (InvalidOperation, ValueError):
            return str(value)
    return str(value)
