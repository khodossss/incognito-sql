"""The harness reads every channel: a gateway leaking through any one of them is caught."""

import json
import logging
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from bench.cases import Case
from bench.harness import Run, log_text, open_runs, run_case
from bench.judge import judge
from bench.oracle import leaks
from bench.world import World
from incognito_sql.core.budget import Spend

if TYPE_CHECKING:
    from incognito_sql.core.pipeline import Gateway

CANARY = "Zq8g1h9k0m8p"
CASE = Case("probe", "SELECT 1", "safe", None, frozenset({"sqlite"}), "both", "ours", "x")
# The chain digest's letters, read as base64, hold a piece of CHANCE: chance, not data.
CHANCE = "Zq9n1y8n8j9z"
DIGEST = "iefmpgioghcncboolgdiknlhcoombfdbabbmbjigajmeejkdpabpffdebilkehek"
LINE = {
    "ts": "2026-10-29T22:13:05.188901+00:00",
    "outcome": "ok",
    "sql_tokenized": "SELECT 1",
    "prev": DIGEST,
}


class _Leaky:
    """Stands in for a gateway that leaks through one channel and audits ``lines`` times."""

    def __init__(self, channel: str, audit: Path, lines: int = 1) -> None:
        self.channel = channel
        self.audit = audit
        self.lines = lines

    def query(self, sql: str, connection_id: str) -> dict[str, Any]:
        assert (sql, connection_id) == ("SELECT 1", "bench-x")
        if self.channel == "stderr":
            sys.stderr.write(f"oops {CANARY}\n")
        if self.channel == "log":
            logging.getLogger("incognito_sql.core.pipeline").warning("failed on %s", CANARY)
        if self.channel == "warning":
            warnings.warn(f"odd value {CANARY}", UserWarning, stacklevel=1)
        line = {**LINE, "sql_tokenized": CANARY} if self.channel == "audit" else LINE
        with self.audit.open("a", encoding="utf-8") as fh:
            fh.write((json.dumps(line) + "\n") * self.lines)
        if self.channel == "answer":
            return {"rows": [[CANARY.encode().hex()]]}
        return {"rows": []}

    def ask(self, sql: str, connection_id: str) -> tuple[dict[str, Any], Spend]:
        return self.query(sql, connection_id), Spend()


def _run(channel: str, tmp_path: Path, lines: int = 1) -> Run:
    audit = tmp_path / "a.jsonl"
    audit.write_text("", encoding="utf-8")
    return Run(cast("Gateway", _Leaky(channel, audit, lines)), audit)


@pytest.mark.parametrize(
    ("channel", "where"),
    [("stderr", "stderr"), ("log", "stderr"), ("audit", "audit"), ("answer", "answer")],
)
def test_each_channel_is_read(
    channel: str,
    where: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    outcome = run_case(
        _run(channel, tmp_path), CASE, lambda: capsys.readouterr().err + log_text(caplog.records)
    )
    assert judge(CASE, outcome, [CANARY]) == [f"leak in {where}: ['{CANARY}']"]


def test_a_warning_is_scanned_and_fails(tmp_path: Path) -> None:
    outcome = run_case(_run("warning", tmp_path), CASE, str)
    assert judge(CASE, outcome, [CANARY]) == [
        f"leak in warnings: ['{CANARY}']",
        f"warnings: ['UserWarning: odd value {CANARY}']",
    ]


@pytest.mark.parametrize("lines", [0, 2])
def test_exactly_one_audit_line_per_case(lines: int, tmp_path: Path) -> None:
    outcome = run_case(_run("none", tmp_path, lines), CASE, str)
    assert judge(CASE, outcome, []) == [f"{lines} audit lines, expected 1"]


def test_audit_clock_is_not_scanned(tmp_path: Path) -> None:
    outcome = run_case(_run("none", tmp_path), CASE, str)
    assert "188901" not in outcome.channels["audit"]
    assert '"sql_tokenized": "SELECT 1"' in outcome.channels["audit"]


def test_audit_chain_is_not_scanned(tmp_path: Path) -> None:
    assert leaks(json.dumps(LINE), [CHANCE]) == [CHANCE]  # the digest alone trips the oracle
    outcome = run_case(_run("none", tmp_path), CASE, str)
    assert DIGEST not in outcome.channels["audit"]
    assert judge(CASE, outcome, [CHANCE]) == []


def test_the_audit_read_is_the_one_the_gateway_appends_to(runs: dict[str, Run]) -> None:
    for run in runs.values():
        run.read_audit()
        run.gateway.query("SELECT id FROM users WHERE id = 1", "bench-audit")
        assert len(run.read_audit()) == 1  # the file the gateway really appends to


def test_debug_records_stay_off_stderr(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    logging.getLogger("incognito_sql.core.exec").debug("raw driver text %s", CANARY)
    assert CANARY not in log_text(caplog.records)  # the CLI prints WARNING and above only


def test_the_mode_pair_opens_under_a_named_profile(world: World, world_db: Path) -> None:
    dsn = f"sqlite:///{world_db.as_posix()}"
    opened = open_runs(world_db.parent, world, "sqlite", dsn, protection="balanced")
    try:
        assert {name: run.protection for name, run in opened.items()} == {
            "web": "balanced",
            "labels": "balanced",
        }
        assert (world_db.parent / "bench-labels-balanced.yaml").exists()
        assert opened["web"].tokens["TOKEN_OWN"].startswith("tk_")
    finally:
        for run in opened.values():
            run.gateway.close()
