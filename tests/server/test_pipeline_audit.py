"""The pipeline in the declared dialect, and what the audit line and the log say."""

import json
import logging
import sqlite3
from types import SimpleNamespace

import pytest

from incognito_sql.core import pipeline
from incognito_sql.core.pipeline import Gateway

from .conftest import GatewayFactory, World

CONN = "c1"


def _audit(world: World) -> list[dict[str, object]]:
    return [json.loads(x) for x in world.audit.read_text(encoding="utf-8").splitlines()]


def test_sqlite_names_fold_case_as_sqlite_does(world: World, make_gateway: GatewayFactory) -> None:
    con = sqlite3.connect(world.db)
    con.execute("ALTER TABLE orders RENAME COLUMN amount TO Amount")
    con.commit()
    con.close()
    out = make_gateway("").query("SELECT amount FROM orders WHERE id = 10", CONN)
    assert out["rows"] == [[100]]


def test_the_query_is_read_and_audited_in_the_declared_dialect(
    gateway: Gateway, world: World
) -> None:
    out = gateway.query("SELECT IIF(`amount` > 50, 'big', 'small') FROM orders WHERE id = 10", CONN)
    assert out["rows"] == [["big"]]
    [line] = _audit(world)
    assert "IIF(" in str(line["sql_tokenized"])


def test_audit_ms_is_the_elapsed_milliseconds(
    gateway: Gateway, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(pipeline, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    gateway.query("SELECT id FROM people", CONN)
    assert _audit(world)[0]["ms"] == 2500


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_failure_is_logged_by_its_type(
    gateway: Gateway, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(pipeline, "shape", lambda *_, **__: 1 / 0)
    with caplog.at_level(logging.DEBUG):
        gateway.query("SELECT id FROM people", CONN)
    assert _warnings(caplog) == ["query failed: ZeroDivisionError"]


def test_a_failed_audit_is_logged_by_its_type(
    gateway: Gateway, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(**_: object) -> None:
        raise PermissionError

    real = gateway._audit  # noqa: SLF001 -- its anchor is closed with the gateway
    monkeypatch.setattr(gateway, "_audit", SimpleNamespace(record=broken, close=real.close))
    with caplog.at_level(logging.DEBUG):
        assert gateway.query("SELECT id FROM people", CONN) == {"error": "internal_error"}
    assert _warnings(caplog) == ["audit failed: PermissionError"]
