"""`check` tells a closed setup from a convenient one, and names each hole with its fix."""

import io
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from incognito_sql.check.clients import client_findings, client_settings
from incognito_sql.check.probes import (
    Access,
    Finding,
    access,
    environment_findings,
    keyring_finding,
)
from incognito_sql.check.run import CLOSED, OPEN, UNKNOWN, findings, report
from incognito_sql.connect.clients import stdio
from incognito_sql.connect.write import updated

CONFIG = "dsn_env: SHOP_DSN\ndialect: sqlite\ncolumns: {people: {id: open}}\nentities: []\n"


def _nothing(_service: str, _user: str) -> str | None:
    return None


def _held(_service: str, _user: str) -> str | None:
    return "a2V5"


def _run(found: list[Finding]) -> tuple[int, str]:
    out = io.StringIO()
    code = report(found, out)
    return code, out.getvalue()


@pytest.fixture
def denied(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], Path]:
    # Opening a marked path is refused, as a file of another OS user is. A folder at the
    # file's place would not do: Linux refuses it as a folder, not as denied. Linux runs
    # the real thing in tests/integration/test_closed_profile.py.
    marked: set[Path] = set()
    real = Path.open

    def guarded(path: Path, *rest: Any, **named: Any) -> Any:  # noqa: ANN401 -- passes its arguments on
        if path in marked:
            raise PermissionError(13, "Permission denied")
        return real(path, *rest, **named)

    monkeypatch.setattr(Path, "open", guarded)

    def mark(path: Path) -> Path:
        marked.add(path)
        return path

    return mark


def test_a_user_who_reaches_nothing_is_closed(
    tmp_path: Path, denied: Callable[[Path], Path]
) -> None:
    service = tmp_path / "service"
    denied(service / "shop.tokens.db")
    found = findings(
        service / "shop.yaml",
        denied(service / "secrets.env"),
        denied(service / "shop.db"),
        environ={},
        home=tmp_path,
        cwd=tmp_path,
        get_password=_nothing,
    )
    code, text = _run(found)
    assert code == CLOSED
    assert "profile: closed" in text
    assert "OPEN" not in text
    assert "note:" not in text  # the database file was probed


def test_without_a_database_file_closed_says_what_it_did_not_probe(
    tmp_path: Path, denied: Callable[[Path], Path]
) -> None:
    service = tmp_path / "service"
    denied(service / "shop.tokens.db")
    found = findings(
        service / "shop.yaml",
        denied(service / "secrets.env"),
        environ={},
        home=tmp_path,
        cwd=tmp_path,
        get_password=_nothing,
    )
    code, text = _run(found)
    assert code == CLOSED
    assert "no database file was probed" in text


@pytest.mark.parametrize("named", [True, False])
def test_missing_paths_or_none_give_unknown(tmp_path: Path, *, named: bool) -> None:
    paths = (tmp_path / "typo.yaml", tmp_path / "typo.env") if named else (None, None)
    found = findings(*paths, environ={}, home=tmp_path, cwd=tmp_path, get_password=_nothing)
    code, text = _run(found)
    assert code == UNKNOWN
    assert "profile: unknown" in text
    assert "profile: closed" not in text


def test_every_reachable_secret_is_a_hole_with_a_fix(tmp_path: Path) -> None:
    db = tmp_path / "shop.db"
    with closing(sqlite3.connect(db)):
        pass
    config = tmp_path / "shop.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    (tmp_path / "shop.tokens.db").write_bytes(b"")
    secrets = tmp_path / "secrets.env"
    secrets.write_text("SHOP_DSN=x\n", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {"mcpServers": {"shop": {"command": "incognito-sql", "env": {"SHOP_DSN": "x"}}}}
        ),
        encoding="utf-8",
    )
    environ = {"SHOP_DSN": f"sqlite:///{db.as_posix()}", "INCOGNITO_SQL_KEY": "k"}
    found = findings(
        config, secrets, environ=environ, home=tmp_path, cwd=tmp_path, get_password=_held
    )
    code, text = _run(found)
    assert code == OPEN
    assert "profile: convenient" in text
    for hole in (
        "secrets file",
        "token store",
        "INCOGNITO_SQL_KEY in this environment",
        "SHOP_DSN in this environment",
        "OS keyring",
        "starts incognito-sql as this user, with its secrets in the file",
        "database file",
    ):
        fixes = [line for line in text.splitlines() if line.startswith("  fix: ")]
        assert any(hole in line for line in fixes), hole
    assert str(tmp_path) not in text  # client files are named by label, not by path
    assert text.count("  fix: ") == sum(f.hole for f in found) == 7


def test_only_clients_that_start_the_server_are_flagged(tmp_path: Path) -> None:
    settings = tmp_path / ".claude.json"
    settings.write_text(
        json.dumps(
            {
                "projects": {
                    "C:/work": {
                        "mcpServers": {
                            "stdio": {"command": "uvx", "args": ["incognito-sql", "serve"]},
                            "module": {"command": "python", "args": ["-m", "incognito_sql"]},
                            "http": {"type": "http", "url": "http://127.0.0.1:8766/mcp"},
                            "other": {"command": "postgres-mcp"},
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    found = client_findings([("a", settings), ("b", broken), ("c", tmp_path / "missing.json")])
    assert len(found) == 2  # the script and `python -m incognito_sql`, not http or others
    assert all(f.hole and "with its secrets" not in f.what for f in found)


def test_a_login_with_a_password_anywhere_in_the_environment_is_a_hole() -> None:
    found = environment_findings(
        {
            "PG": "postgresql+psycopg://reader:pw@db:5432/shop",
            "LITE": "sqlite:///x.db",
            "HTTPS_PROXY": "http://me:pw@proxy:8080",
        },
        None,
    )
    holes = [f.what for f in found if f.hole]
    assert holes == ["database login with a password in PG"]


def test_the_keyring_is_probed() -> None:
    assert not keyring_finding(_nothing).hole
    assert keyring_finding(_held).hole


def test_a_broken_keyring_holds_nothing() -> None:
    def broken(_service: str, _user: str) -> str | None:
        raise RuntimeError

    assert not keyring_finding(broken).hole


@pytest.mark.parametrize(
    ("client", "where"),
    [
        ("codex", Path("codex") / "config.toml"),
        ("opencode", Path("opencode.json")),
        ("cursor", Path(".cursor") / "mcp.json"),
    ],
)
def test_check_finds_what_connect_wrote(client: str, where: Path, tmp_path: Path) -> None:
    server = stdio(
        "shop", tmp_path / "shop.yaml", "SHOP_DSN", "sqlite", release="0.4.0", python="python"
    )
    path = tmp_path / where
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated(client, server, ""), encoding="utf-8")
    environ = {"CODEX_HOME": str(tmp_path / "codex")}
    found = client_findings(client_settings(tmp_path / "home", tmp_path, environ))
    assert len(found) == 1, client
    assert found[0].hole
    assert "with its secrets" not in found[0].what  # only references to variables
    assert str(tmp_path) not in found[0].what


def test_a_literal_secret_in_a_client_entry_is_named(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "s": {
                        "command": ["incognito-sql", "serve"],
                        "environment": {"SHOP_DSN": "sqlite:///x"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    found = client_findings(client_settings(tmp_path, tmp_path, {}))
    assert [f.what for f in found] == [
        (
            "OpenCode project file (opencode.json) starts incognito-sql as this user, "
            "with its secrets in the file"
        )
    ]


def test_a_path_this_os_cannot_name_proves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid(*_: object, **__: object) -> None:
        raise OSError(22, "Invalid argument")  # what Windows says of a name with `:` or `<`

    monkeypatch.setattr(Path, "open", invalid)
    assert access(tmp_path / "x") is Access.MISSING
