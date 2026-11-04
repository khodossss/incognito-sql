"""incognito-sql, in process: one gateway per output mode, as the corpus harness opens it.

Each query goes through ``bench.harness.run_case`` (the same path the attack-corpus
tests use), so the answer, the new audit lines, WARNING+ log records, anything written
to ``sys.stderr`` and raised warnings are all collected for the oracle.
"""

import contextlib
import io
import json
import logging
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import anyio
from mcp import Client

from bench.adapters.base import ANSWERED, ERROR, REFUSED, Info, Outcome, timed
from bench.cases import Case
from bench.dbms import Database
from bench.harness import MODES, Run, log_text, open_runs, run_case
from bench.profiles import row_name
from bench.world import World
from incognito_sql.mcp.server import build_server

INFOS = {
    mode: Info(
        name=f"incognito-sql ({mode})",
        mechanism=f"checked AST, regenerated SQL; identifiers as {kind}",
        rung=5 + i,
        version="this repository",
        source="https://github.com/khodossss/incognito-sql",
        install="uv sync",
        command="in process: wiring.open_gateway, as incognito-sql serve composes it",
        tool="query",
        arguments="sql",
        strict=True,
    )
    for i, (mode, kind) in enumerate((("web", "web-card links"), ("labels", "labels")))
}


class IncognitoAdapter:
    """One output mode of incognito-sql over the bench world."""

    def __init__(self, run: Run, mode: str, dialect: str) -> None:
        """Wrap an opened gateway and its audit file."""
        self.info, self.mode, self.dialect, self._run = INFOS[mode], mode, dialect, run
        self.tokens: Mapping[str, str] = run.tokens
        self._pending: dict[str, str] = {}

    def query(self, sql: str) -> Outcome:
        """Send one query; keep its audit, stderr and warning text for ``channels``."""
        case = Case("bench", sql, "safe", None, frozenset(), "both", "ours", "run")
        holder: dict[str, Any] = {}
        spent: list[tuple[int, int]] = []

        def call() -> tuple[str, str, list[list[object]] | None]:
            with _stderr() as read:
                outcome = run_case(self._run, case, read)
            holder.update(outcome.channels)
            spent.append(outcome.spend)
            answer = outcome.answer
            error = answer.get("error")
            status = ANSWERED if error is None else ERROR if error == "internal_error" else REFUSED
            rows = answer.get("rows")
            return status, holder["answer"], rows if isinstance(rows, list) else None

        result = timed(call)
        self._pending = {k: v for k, v in holder.items() if k != "answer"}
        return replace(result, spend=spent[0]) if spent else result

    def channels(self) -> dict[str, str]:
        """Return the side-channel text of the last query."""
        pending, self._pending = self._pending, {}
        return pending

    def static(self) -> str:
        """Return ``describe()`` and the MCP instructions and tool listing."""
        gateway, seen = self._run.gateway, dict[str, object]()

        async def listing() -> None:
            async with Client(build_server(gateway, "bench-tools")) as client:
                seen["instructions"] = client.instructions or ""
                seen["tools"] = [
                    t.model_dump(mode="json") for t in (await client.list_tools()).tools
                ]

        anyio.run(listing)
        return json.dumps([gateway.describe(), seen], ensure_ascii=False, default=str)

    def close(self) -> None:
        """Close the gateway."""
        self._run.gateway.close()


def profile_infos(profiles: Sequence[str]) -> list[Info]:
    """Return the row of each output mode under each of ``profiles``."""
    return [replace(INFOS[m], name=row_name(INFOS[m].name, p)) for p in profiles for m in MODES]


def open_incognito(
    world: World, db: Database, workdir: Path, profiles: Sequence[str] = ()
) -> list[IncognitoAdapter]:
    """Open both output modes over ``db`` as its reader.

    With ``profiles``, a pair of rows per profile, named by it; without, the server as the
    corpus expects it (strict), named by mode only.
    """
    adapters: list[IncognitoAdapter] = []
    try:
        for profile in profiles or ("strict",):
            runs = open_runs(workdir, world, db.dialect, db.url, protection=profile)
            for mode in MODES:
                adapter = IncognitoAdapter(runs[mode], mode, db.dialect)
                if profiles:
                    adapter.info = replace(adapter.info, name=row_name(adapter.info.name, profile))
                adapters.append(adapter)
    except Exception:
        for adapter in adapters:
            adapter.close()
        raise
    return adapters


class _Collect(logging.Handler):
    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(logging.WARNING)
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextlib.contextmanager
def _stderr() -> Iterator[Any]:
    """Collect ``sys.stderr`` writes and WARNING+ records while the query runs."""
    records: list[logging.LogRecord] = []
    handler = _Collect(records)
    root, buffer = logging.getLogger(), io.StringIO()
    root.addHandler(handler)
    try:
        with contextlib.redirect_stderr(buffer):
            yield lambda: buffer.getvalue() + log_text(records)
    finally:
        root.removeHandler(handler)
