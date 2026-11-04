"""Printed commands are quoted for the operator's shell: PowerShell on Windows, else POSIX."""

import base64
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from incognito_sql import shell
from incognito_sql.cli import main
from incognito_sql.connect.clients import block, stdio

TYPOGRAPHIC = chr(0x2019)  # PowerShell ends a quoted string at it as at an apostrophe
AWKWARD = rf"C:\Users\Jo O'Neil\My Shop{TYPOGRAPHIC}s\shop.yaml"  # and spaces
WORDS = ["--config", AWKWARD, "--", "x=${X}", "a,b", "@all", "$HOME", "", "plain-word"]


@pytest.mark.parametrize("windows", [True, False])
def test_each_form_quotes_an_awkward_path(
    monkeypatch: pytest.MonkeyPatch, *, windows: bool
) -> None:
    monkeypatch.setattr(shell, "WINDOWS", windows)
    line = shell.join(["incognito-sql", "check", "--config", AWKWARD])
    if windows:
        quoted = rf"'C:\Users\Jo O''Neil\My Shop{TYPOGRAPHIC * 2}s\shop.yaml'"
        assert line == f"incognito-sql check --config {quoted}"
    else:
        assert shlex.split(line) == ["incognito-sql", "check", "--config", AWKWARD]


@pytest.mark.skipif(shutil.which("powershell") is None, reason="needs Windows PowerShell")
def test_powershell_reads_its_form_back() -> None:
    code = "import sys; print(ascii(sys.argv[1:]))"
    words = [shell.powershell(w) for w in (sys.executable, "-c", code, *WORDS)]
    script = "& " + " ".join(words)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    run = subprocess.run(  # noqa: S603 -- our own interpreter, our own words
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    assert run.stdout.strip() == ascii([w for w in WORDS if w])  # 5.1 drops an empty word


@pytest.mark.parametrize("windows", [True, False])
def test_claude_code_s_command_is_in_the_operator_s_form(
    monkeypatch: pytest.MonkeyPatch, *, windows: bool
) -> None:
    monkeypatch.setattr(shell, "WINDOWS", windows)
    line = block(
        "claude-code", stdio("shop", Path(AWKWARD), "SHOP_DSN", "sqlite", release=None, python="py")
    )
    assert ("O''Neil" in line) is windows
    assert "'SHOP_DSN=${SHOP_DSN}'" in line  # single quotes: neither shell expands it
    if not windows:  # the entry names the config by its absolute path, as the OS resolves it
        assert str(Path(AWKWARD).resolve()) in shlex.split(line)


@pytest.mark.parametrize("windows", [True, False])
def test_demo_says_how_to_set_the_dsn_in_the_operator_s_shell(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    windows: bool,
) -> None:
    monkeypatch.setattr(shell, "WINDOWS", windows)
    folder = tmp_path / "Jo O'Neil"
    assert main(["demo", str(folder)]) == 0
    out = capsys.readouterr().out
    assert ("$env:DEMO_SHOP_DSN = 'sqlite:///" in out) is windows
    assert ("[Environment]::SetEnvironmentVariable('DEMO_SHOP_DSN', " in out) is windows
    assert ("restart the client" in out) is windows
    assert ("export DEMO_SHOP_DSN=" in out) is not windows
    assert ("O''Neil" in out) is windows
