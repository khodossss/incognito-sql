"""Closed profile on Linux: the agent's account reaches the service only by MCP with the token."""

import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
IMAGE = "python:3.13-slim"
TOKEN = "closed-profile-token-" + "x" * 24
KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="  # base64 of bytes 0..31, invented
CONFIG = """dsn_env: SHOP_DSN
dialect: sqlite
web_port: 8775
mcp_port: 8776
columns: {people: {id: open, full_name: identifier}}
entities: [{table: people, pk: id}]
"""


def _fixture(folder: Path) -> None:
    folder.mkdir()
    with closing(sqlite3.connect(folder / "shop.db")) as con:
        con.executescript(
            "CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT);"
            "INSERT INTO people VALUES (1, 'Zqclosed Person');"
        )
        con.commit()
    # The container's shell reads these: no carriage returns.
    (folder / "shop.yaml").write_text(CONFIG, encoding="utf-8", newline="\n")
    (folder / "secrets.env").write_text(
        "SHOP_DSN=sqlite:////srv/incognito/shop.db\n"
        f"INCOGNITO_SQL_KEY={KEY}\nINCOGNITO_SQL_MCP_TOKEN={TOKEN}\n",
        encoding="utf-8",
        newline="\n",
    )
    shutil.copy(HERE / "closed_profile_probe.py", folder / "probe.py")


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dist = tmp_path_factory.mktemp("dist")
    subprocess.run(  # noqa: S603 -- fixed command
        ["uv", "build", "--wheel", "--out-dir", str(dist)],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return dist


def _observe(dist: Path, tmp_path: Path, mode: str) -> dict[str, str]:
    fixture = tmp_path / "fixture"
    _fixture(fixture)
    script = (HERE / "closed_profile.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    done = subprocess.run(  # noqa: S603 -- fixed command
        [  # noqa: S607
            "docker",
            "run",
            "--rm",
            "-e",
            f"MODE={mode}",
            "-v",
            f"{dist}:/dist:ro",
            "-v",
            f"{fixture}:/fixture:ro",
            IMAGE,
            "sh",
            "-c",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    lines = [line for line in done.stdout.splitlines() if "=" in line]
    seen = dict(line.split("=", 1) for line in lines)
    assert seen.get("install") != "failed", done.stdout
    # The probes ran as the agent, with the command installed: exit codes mean access.
    assert (seen["agent_is"], seen["agent_has_cli"]) == ("agent", "0"), seen
    return seen


def test_the_agent_user_reaches_nothing_but_mcp_with_the_token(wheel: Path, tmp_path: Path) -> None:
    seen = _observe(wheel, tmp_path, "closed")
    assert seen["check"] == "0", seen  # check reports "closed"
    # cat: 1 = permission denied; login: 2 = the secrets file cannot be read
    expected = {"read_secrets": "1", "read_db": "1", "read_tokens": "1", "login": "2"}
    assert {k: seen[k] for k in expected} == expected, seen
    assert (seen["mcp_without_token"], seen["mcp_with_token"]) == ("401", "200"), seen
    assert seen["login_as_service"] == "1", seen  # the service's own account can sign in


def test_without_the_folder_lock_the_agent_reaches_the_secrets(wheel: Path, tmp_path: Path) -> None:
    seen = _observe(wheel, tmp_path, "open")
    assert seen["check"] == "1", seen  # check reports "convenient"
    expected = {"read_secrets": "0", "read_db": "0", "read_tokens": "0"}
    assert {k: seen[k] for k in expected} == expected, seen
