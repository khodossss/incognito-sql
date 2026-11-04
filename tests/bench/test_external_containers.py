"""Competitor launches on a set's file: veil gets the long start its seeding needs."""

from pathlib import Path

import pytest
from external_world import QUESTIONS, RECORDS, build

from bench.adapters import launch
from bench.adapters.mcp_stdio import START_S
from bench.external import containers
from bench.external.work import works


def test_only_veil_waits_longer_than_the_default_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "ensure_image", lambda tag, **_: tag)
    path, marking = build(tmp_path)
    work = next(iter(works(path, marking, QUESTIONS, RECORDS)))
    plans = {
        "veil": containers._veil(work),  # noqa: SLF001
        "gate": containers._gate(work),  # noqa: SLF001
        "januscope": containers._januscope(work),  # noqa: SLF001
        "db-mcp-server": containers._freepeak(work),  # noqa: SLF001
        "dbmcp": containers._dbmcp(work),  # noqa: SLF001
    }
    assert plans.pop("veil").start_s == containers.VEIL_START_S > START_S
    assert {plan.start_s for plan in plans.values()} == {START_S}
    assert plans["gate"].env["DSN"] == "sqlite:///data/shop.sqlite"
    assert "veil/schema.prisma" in containers._veil(work).files  # noqa: SLF001
