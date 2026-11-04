"""`incognito-sql secret`: typed hidden in the human's terminal, kept by name, never shown."""

import argparse
import os
import stat
import sys
from pathlib import Path

import pytest

from incognito_sql.envfile import load_env_file
from incognito_sql.setup.secret import Terminal, add_secret_parser, run_secret

PASSWORD = "Zq7 s3cr@t/pw%"  # noqa: S105 -- invented; spaces and URL characters on purpose


@pytest.fixture(autouse=True)
def _clean_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    # `secret` sets what it keeps in this process too: setenv first records the variable's
    # absence, so the teardown removes what the test left (delenv of an absent one records
    # nothing).
    for name in ("SHOP_DSN", "INCOGNITO_SQL_KEY", "INCOGNITO_SQL_MCP_TOKEN"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


def _run(
    *argv: str, typed: tuple[str, ...] = (PASSWORD, PASSWORD), terminal: bool = True
) -> tuple[int, dict[str, str]]:
    parser = argparse.ArgumentParser()
    add_secret_parser(parser.add_subparsers(dest="command"))
    entries, kept = iter(typed), dict[str, str]()
    term = Terminal(terminal, lambda _: next(entries), kept.__setitem__)
    return run_secret(parser.parse_args(["secret", *argv]), term), kept


def _shown(capsys: pytest.CaptureFixture[str]) -> str:
    out = capsys.readouterr()
    return out.out + out.err


def test_a_template_takes_the_password_encoded(capsys: pytest.CaptureFixture[str]) -> None:
    code, kept = _run("SHOP_DSN", "--template", "postgresql+psycopg://reader:{password}@db/shop")
    assert code == 0
    assert kept == {"SHOP_DSN": "postgresql+psycopg://reader:Zq7%20s3cr%40t%2Fpw%25@db/shop"}
    assert os.environ["SHOP_DSN"] == kept["SHOP_DSN"]  # the next step in this process reads it
    shown = _shown(capsys)
    assert "SHOP_DSN set" in shown
    assert "Zq7" not in shown


def test_an_env_file_gets_one_line_readable_by_its_owner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / "secrets.env"
    env.write_text('OTHER=1\nSHOP_DSN="old"\n', "utf-8")
    assert _run("SHOP_DSN", "--env-file", str(env))[0] == 0
    read: dict[str, str] = {}
    load_env_file(env, read)
    assert read == {"OTHER": "1", "SHOP_DSN": PASSWORD}
    if sys.platform != "win32":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "Zq7" not in _shown(capsys)


@pytest.mark.parametrize(
    ("argv", "typed", "terminal", "code"),
    [
        (("SHOP_DSN",), (PASSWORD, PASSWORD), False, 1),  # an agent's shell: no terminal
        (("SHOP_DSN",), (PASSWORD, "other"), True, 1),  # the two entries differ
        (("SHOP_DSN",), ("", ""), True, 1),
        ((PASSWORD,), (), True, 2),  # a value where the name goes
        (("SHOP_DSN", "--template", "pg://u@h/db"), (), True, 2),  # no {password}
        (("SHOP_DSN", "--template", "{password}", "--generate", "key"), (), True, 2),
    ],
)
def test_nothing_is_kept_and_nothing_repeated(
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    typed: tuple[str, ...],
    *,
    terminal: bool,
    code: int,
) -> None:
    assert _run(*argv, typed=typed, terminal=terminal) == (code, {})
    assert "Zq7" not in _shown(capsys).replace("SHOP_DSN", "")


def test_without_a_user_variable_an_env_file_is_asked_for(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = argparse.ArgumentParser()
    add_secret_parser(parser.add_subparsers(dest="command"))
    term = Terminal(present=True, hidden=lambda _: PASSWORD, for_user=None)
    assert run_secret(parser.parse_args(["secret", "SHOP_DSN"]), term) == 2
    assert "--env-file" in _shown(capsys)


def test_a_generated_key_is_shown_to_nobody(capsys: pytest.CaptureFixture[str]) -> None:
    code, kept = _run("INCOGNITO_SQL_KEY", "--generate", "key", typed=())
    assert code == 0
    assert kept["INCOGNITO_SQL_KEY"] not in _shown(capsys)


def test_a_generated_token_is_shown_once(capsys: pytest.CaptureFixture[str]) -> None:
    code, kept = _run("INCOGNITO_SQL_MCP_TOKEN", "--generate", "token", typed=())
    assert code == 0
    token = kept["INCOGNITO_SQL_MCP_TOKEN"]
    assert len(token) >= 32
    assert _shown(capsys).count(token) == 1
