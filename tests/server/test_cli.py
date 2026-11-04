"""`incognito-sql serve --config PATH`: arguments, missing DSN, quiet logging."""

import logging
import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from incognito_sql import cli
from incognito_sql.core.budget import SESSIONLESS
from incognito_sql.core.pipeline import Gateway
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.mcp import server as mcp_server
from incognito_sql.web.run import bind_local

from .conftest import CONFIG, DSN_ENV, World

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    ours = logging.getLogger("incognito_sql")
    level = ours.level
    yield
    ours.setLevel(level)


@pytest.mark.parametrize("argv", [[], ["serve"], ["web"], ["serve", "--bogus"]])
def test_bad_arguments_exit_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(argv)
    assert caught.value.code == 2


def test_missing_dsn_names_the_variable(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(DSN_ENV)
    assert cli.main(["serve", "--config", str(world.config)]) == 2
    assert DSN_ENV in capsys.readouterr().err


def test_serve_runs_the_server_over_stdio(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[MCPServer] = []
    monkeypatch.setattr(cli, "_run_stdio", started.append)
    assert cli.main(["serve", "--config", str(world.config)]) == 0
    [server] = started
    assert server.name == "incognito-sql"
    assert (world.config.parent / "field.tokens.db").exists()
    assert world.audit.exists()
    assert not logging.getLogger("incognito_sql.core.exec").isEnabledFor(logging.DEBUG)


def _start_error(capsys: pytest.CaptureFixture[str], world: World, code: int) -> str:
    assert cli.main(["serve", "--config", str(world.config)]) == code
    err = capsys.readouterr().err
    assert err.startswith("incognito-sql: ")
    assert err.count("\n") == 1  # one line, no traceback
    return err


def test_failed_open_is_one_line_without_the_dsn(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dsn = f"sqlite:///{world.db.parent / 'Zzmissing.db'}"
    monkeypatch.setenv(DSN_ENV, dsn)
    err = _start_error(capsys, world, 1)
    assert "cannot open the database" in err
    assert "zzmissing" not in err.casefold()
    (world.config.parent / "field.tokens.db").unlink()  # closed again after the failure


VIEWED = CONFIG.replace("columns:\n", "columns:\n  towns: {city: quasi}\n") + (
    "row_rules: [{table: people, hide: [city], where: 'id = 1'}]\n"
)


def test_an_open_view_without_a_row_rule_stops_the_start(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with closing(sqlite3.connect(world.db)) as con:
        con.execute("CREATE VIEW towns AS SELECT city FROM people")
    world.config.write_text(VIEWED, encoding="utf-8")
    err = _start_error(capsys, world, 2)
    assert "towns: open, a view" in err
    world.config.write_text(VIEWED + "verified_relations: [Towns]\n", encoding="utf-8")
    started: list[MCPServer] = []
    monkeypatch.setattr(cli, "_run_stdio", started.append)
    assert cli.main(["serve", "--config", str(world.config)]) == 0
    assert started


def test_bad_config_and_bad_key_are_one_line(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INCOGNITO_SQL_KEY", "not-a-key")
    assert "INCOGNITO_SQL_KEY" in _start_error(capsys, world, 1)
    world.config.write_text("dsn_env: [", encoding="utf-8")
    assert "cannot read the config" in _start_error(capsys, world, 1)
    world.write_config("foreign_keys: []\n")
    assert "top level: unknown key" in _start_error(capsys, world, 1)


def test_domain_survives_a_password_change() -> None:
    cipher = Cipher(bytes(range(32)))
    one = cli.token_domain(cipher, "postgresql://app:Zzold@db.local:5432/crm?sslmode=require")
    two = cli.token_domain(cipher, "postgresql://app:Zznew@db.local:5432/crm?sslmode=require")
    other = cli.token_domain(cipher, "postgresql://app:Zzold@db.local:5432/hr?sslmode=require")
    assert one == two != other
    assert one.startswith("db:")


SERVICE_TOKEN = "t" * 40


def test_service_runs_the_server_over_http_with_the_token(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started: list[tuple[int, str, MCPServer]] = []

    def fake_http(port: int, token: str) -> Callable[["MCPServer"], None]:
        return lambda server: started.append((port, token, server))

    budgets: list[str] = []
    build = mcp_server.build_server

    def counted(gateway: Gateway, connection_id: str) -> "MCPServer":
        budgets.append(connection_id)
        return build(gateway, connection_id)

    monkeypatch.setattr(cli, "_run_http", fake_http)
    monkeypatch.setattr(mcp_server, "build_server", counted)
    monkeypatch.setenv("INCOGNITO_SQL_MCP_TOKEN", SERVICE_TOKEN)
    world.write_config("mcp_port: 9123\nweb_enabled: false\n")
    assert cli.main(["service", "--config", str(world.config)]) == 0
    assert budgets == [SESSIONLESS]
    [(port, token, server)] = started
    assert (port, token, server.name) == (9123, SERVICE_TOKEN, "incognito-sql")
    assert "http://127.0.0.1:9123/mcp" in capsys.readouterr().err


def test_service_without_a_token_is_one_line(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("INCOGNITO_SQL_MCP_TOKEN", raising=False)
    assert cli.main(["service", "--config", str(world.config)]) == 2
    assert "INCOGNITO_SQL_MCP_TOKEN" in capsys.readouterr().err


def test_the_env_file_supplies_unset_secrets(
    world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dsn, key = os.environ[DSN_ENV], os.environ["INCOGNITO_SQL_KEY"]
    monkeypatch.delenv(DSN_ENV)
    monkeypatch.delenv("INCOGNITO_SQL_KEY")
    secrets = tmp_path / "secrets.env"
    secrets.write_text(f"{DSN_ENV}={dsn}\nINCOGNITO_SQL_KEY={key}\n", encoding="utf-8")
    started: list[MCPServer] = []
    monkeypatch.setattr(cli, "_run_stdio", started.append)
    argv = ["serve", "--config", str(world.config), "--env-file", str(secrets)]
    assert cli.main(argv) == 0
    assert len(started) == 1


def test_a_bad_env_file_is_one_line(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["serve", "--config", str(world.config), "--env-file", str(tmp_path / "none.env")]
    assert cli.main(argv) == 2
    assert capsys.readouterr().err.count("\n") == 1


def test_check_reports_this_test_process_as_convenient(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    # The fixture put the DSN and the key in this process's environment: holes.
    assert cli.main(["check", "--config", str(world.config)]) == 1
    out = capsys.readouterr().out
    assert "INCOGNITO_SQL_KEY in this environment" in out
    assert "profile: convenient" in out


def test_service_will_not_start_beside_a_squatted_cards_port(
    world: World,
    free_port: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    started: list[MCPServer] = []
    monkeypatch.setattr(cli, "_run_http", lambda _port, _token: started.append)
    monkeypatch.setenv("INCOGNITO_SQL_MCP_TOKEN", SERVICE_TOKEN)
    world.write_config(f"web_port: {free_port}\n")
    squatter = bind_local(free_port)  # whoever holds it would get the sign-in links
    assert squatter is not None
    try:
        assert cli.main(["service", "--config", str(world.config)]) == 1
    finally:
        squatter.close()
    assert started == []
    assert f"port {free_port}" in capsys.readouterr().err
