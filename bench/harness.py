"""Run corpus cases through the real gateway and collect every channel the oracle reads.

This module composes the server under test; the oracle itself (``bench.oracle``) never
imports it.
"""

import json
import logging
import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bench.cases import Case
from bench.judge import Outcome
from bench.score import unclocked
from bench.templates import expand, spelling_fills, token_fills
from bench.world import World
from incognito_sql.core.config import load_declaration
from incognito_sql.core.pipeline import Gateway
from incognito_sql.wiring import audit_path, open_gateway

KEY = bytes(range(32))
MODES = ("web", "labels")
TOKEN = re.compile(r"tk_[a-z2-7]{16}")
_FORMAT = logging.Formatter("%(levelname)s %(name)s %(message)s")


@dataclass
class Run:
    """One gateway and the audit file it appends to; ``read_audit`` returns only new lines."""

    gateway: Gateway
    audit: Path
    tokens: dict[str, str] = field(default_factory=dict)
    protection: str = "strict"
    _seen: int = 0

    def read_audit(self) -> list[str]:
        """Return the audit lines written since the last call."""
        with self.audit.open("rb") as fh:
            fh.seek(self._seen)
            new = fh.read()
        self._seen += len(new)
        return new.decode("utf-8").splitlines()


def open_runs(  # noqa: PLR0913 -- the world on one DBMS, under which profiles
    directory: Path,
    world: World,
    dialect: str,
    dsn: str,
    profiles: tuple[str, ...] = (),
    *,
    protection: str = "strict",
) -> dict[str, Run]:
    """Open one gateway per mode, each with its own config, token store and audit file.

    The modes run under ``protection``; each name in ``profiles`` adds a run under that
    protection profile, in web mode.
    """
    runs: dict[str, Run] = {}
    suffix = "" if protection == "strict" else f"-{protection}"  # one directory, many calls
    try:
        for name in (*MODES, *profiles):
            under = name if name in profiles else protection
            config = directory / f"bench-{name}{suffix}.yaml"
            web = name != "labels"
            text = world.declaration(dialect, web=web, protection=under)
            config.write_text(text, encoding="utf-8")
            gw = open_gateway(config, load_declaration(config), dsn, KEY)
            runs[name] = Run(gw, audit_path(config), protection=under)
        # Each web-mode run has its own token store: its own token for TOKEN_OWN.
        found = {name: _own_token(run) for name, run in runs.items() if name != "labels"}
    except Exception:
        for run in runs.values():
            run.gateway.close()
        raise
    own = str(world.tables[0].rows[0][1])  # users.name of id 1: the value behind TOKEN_OWN
    for name, run in runs.items():
        run.tokens = token_fills(found.get(name, found["web"])) | spelling_fills(own)
        run.read_audit()  # setup lines belong to no case
    return runs


def _own_token(run: Run) -> str:
    answer = run.gateway.query("SELECT name FROM users WHERE id = 1", "bench-setup")
    found = TOKEN.search(str(answer))
    if found is None:
        msg = f"web mode gave no token: {answer}"
        raise RuntimeError(msg)
    return found.group(0)


def log_text(records: list[logging.LogRecord]) -> str:
    """Format WARNING+ records the way the CLI prints them on stderr."""
    return "\n".join(_FORMAT.format(r) for r in records if r.levelno >= logging.WARNING)


def run_case(run: Run, case: Case, stderr: Callable[[], str]) -> Outcome:
    """Send one case; return the answer and the text of every channel it touched."""
    run.read_audit()  # lines of earlier queries belong to no case
    connection = f"bench-{case.category}"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        setup = [] if case.setup is None else [_send(run, case.setup, connection)]
        prior = run.read_audit()
        answer, spend = run.gateway.ask(expand(case.sql, run.tokens), connection)
    lines = run.read_audit()
    raised = [f"{w.category.__name__}: {w.message}" for w in caught]
    channels = {
        "answer": json.dumps(answer, ensure_ascii=False),
        "audit": "\n".join(map(unclocked, lines)),
        "stderr": stderr(),
        "warnings": "\n".join(raised),
    }
    if setup:
        channels["setup"] = "\n".join([*setup, *map(unclocked, prior)])
    return Outcome(answer, channels, len(lines), raised, (spend.literals, spend.probes))


def _send(run: Run, sql: str, connection: str) -> str:
    return json.dumps(run.gateway.query(expand(sql, run.tokens), connection), ensure_ascii=False)
