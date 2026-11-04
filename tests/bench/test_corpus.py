"""Every corpus case through Gateway.query in both modes on SQLite: zero leaks in any channel."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client

from bench.cases import Case, load_cases
from bench.check import Watch, check_case, selection_problems
from bench.harness import MODES, Run, log_text
from bench.oracle import leaks
from bench.ruled import HIDDEN_KEYS
from bench.world import World
from incognito_sql.core.errors import Reason
from incognito_sql.mcp.server import build_server

CASES = load_cases()
# The two output modes under strict, and the default profile, permissive, in web mode.
RUNS = {**{mode: mode for mode in MODES}, "permissive": "web"}
PARAMS = [
    pytest.param(case, name, id=f"{name}-{case.id}")
    for case in CASES
    for name, mode in RUNS.items()
    if case.runs_in(mode, "sqlite")
]
ORDERED = [pytest.param(c, id=c.id) for c in CASES if c.order_sensitive and "sqlite" in c.dialects]


@pytest.mark.no_cover  # coverage tracing would double the run; unit tests cover the code
@pytest.mark.parametrize(("case", "mode"), PARAMS)
def test_case_does_not_leak(  # noqa: PLR0913, PLR0917 -- pytest fixtures
    case: Case,
    mode: str,
    runs: dict[str, Run],
    world: World,
    watch: Watch,
    capsys: pytest.CaptureFixture[str],  # SQLite: every stderr writer is Python-level
    caplog: pytest.LogCaptureFixture,
    request: pytest.FixtureRequest,
) -> None:
    capsys.readouterr()
    caplog.clear()
    stderr = lambda: capsys.readouterr().err + log_text(caplog.records)  # noqa: E731
    outcome, problems = check_case(
        runs[mode], case, world.gateway_hidden, stderr, watch, hidden_keys=HIDDEN_KEYS
    )
    request.node.user_properties.append(("outcome", outcome.answer.get("error", "answered")))
    assert problems == []


@pytest.mark.no_cover
@pytest.mark.parametrize("case", ORDERED)
def test_selection_varies(case: Case, runs: dict[str, Run], pools: dict[str, int]) -> None:
    assert selection_problems(runs["labels"], case, pools[case.id]) == []


def test_corpus_is_well_formed(world: World) -> None:
    reasons = {r.value for r in Reason}
    assert len(CASES) >= 400
    sources = {"ours", "sql-safe-mcp", "sanitized-db-mcp", "article", "govbench"}
    assert {c.source for c in CASES} == sources
    assert sum(c.source == "article" for c in CASES) == 17
    assert sum(c.source == "govbench" for c in CASES) == 28  # govbench-v1, all of it
    for case in CASES:
        assert case.reason is None or case.reason in reasons, case.id
        # The attacker does not know the canaries: no case may carry one into the audit.
        assert leaks(case.sql, world.forbidden | world.visible) == [], case.id
        assert case.pool is None or leaks(case.pool, world.forbidden) == [], case.id


@pytest.mark.parametrize("mode", MODES)
def test_describe_and_tools_do_not_leak(mode: str, runs: dict[str, Run], world: World) -> None:
    gateway = runs[mode].gateway
    seen: dict[str, Any] = {}

    async def listing() -> None:
        async with Client(build_server(gateway, "bench-tools")) as client:
            seen["instructions"] = client.instructions or ""
            seen["tools"] = [t.model_dump() for t in (await client.list_tools()).tools]

    anyio.run(listing)
    assert len(seen["tools"]) == 2  # query and describe, with descriptions and schemas
    text = json.dumps([gateway.describe(), seen], ensure_ascii=False)
    assert leaks(text, world.forbidden) == []


@pytest.mark.parametrize("mode", MODES)
def test_oracle_sees_open_values(mode: str, runs: dict[str, Run], world: World) -> None:
    answer = runs[mode].gateway.query("SELECT city, tier FROM users", "bench-control")
    assert set(leaks(json.dumps(answer), world.visible)) == set(world.visible)


def test_world_holds_every_canary(world: World, world_db: Path) -> None:
    con = sqlite3.connect(world_db)
    dump = "\n".join(con.iterdump())
    con.close()
    assert set(leaks(dump, world.forbidden)) == world.planted("sqlite") - world.reformatted
