"""Run a prepared query and return capped rows; database errors are sanitized."""

import logging
import re
from dataclasses import dataclass

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.rewrite import Prepared

_LOG = logging.getLogger("incognito_sql.core.exec")
_TOKEN = re.compile(r"tk_", re.IGNORECASE)
_SYNTAX_OR_ACCESS_CLASS = "42"


@dataclass(frozen=True)
class Rows:
    """Result rows as the database returned them, capped at the row limit."""

    columns: list[str]
    rows: list[tuple[object, ...]]
    truncated: bool


def _sqlstate(orig: object) -> str | None:
    for name in ("sqlstate", "pgcode"):
        value = getattr(orig, name, None)
        if isinstance(value, str) and value:
            return value
    return None


def _detail(orig: object, sqlstate: str | None, params: dict[str, object]) -> str | None:
    """Keep the class-42 primary message only if it carries no bound value or token."""
    if sqlstate is None or not sqlstate.startswith(_SYNTAX_OR_ACCESS_CLASS):
        return None
    message = getattr(getattr(orig, "diag", None), "message_primary", None)
    if not isinstance(message, str):
        return None
    folded = message.casefold()
    if _TOKEN.search(message):
        return None
    if any(v and v.casefold() in folded for v in (str(x) for x in params.values())):
        return None
    return message


def _fetch(
    engine: Engine, prepared: Prepared, max_rows: int
) -> Rows | tuple[str | None, str | None]:
    """Run the query; return rows, or (sqlstate, detail) with the raw error left behind.

    Everything raw (driver exception, connection, cursor) lives only in this frame.
    """
    try:
        # The result is closed before the connection: a streaming cursor holds server state.
        with (
            engine.connect().execution_options(stream_results=True) as conn,
            conn.execute(text(prepared.sql), prepared.params) as result,
        ):
            columns = list(result.keys())
            fetched = result.fetchmany(max_rows + 1)
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("database error", exc_info=True)
        orig = exc.orig if isinstance(exc, DBAPIError) else None
        state = _sqlstate(orig)
        return state, _detail(orig, state, prepared.params)
    rows = [tuple(row) for row in fetched[:max_rows]]
    return Rows(columns=columns, rows=rows, truncated=len(fetched) > max_rows)


def execute(engine: Engine, prepared: Prepared, limits: Limits) -> Rows:
    """Run `prepared` and return at most `limits.max_rows` rows.

    Raises `Rejection(DB_ERROR)` on any database error; the error text, the SQL
    and the bound values never leave this function (the full error goes to the
    DEBUG log only).
    """
    if not prepared.sql:
        return Rows(columns=[], rows=[], truncated=False)
    outcome = _fetch(engine, prepared, limits.max_rows)
    if isinstance(outcome, Rows):
        return outcome
    raise Rejection(Reason.DB_ERROR, sqlstate=outcome[0], detail=outcome[1])
