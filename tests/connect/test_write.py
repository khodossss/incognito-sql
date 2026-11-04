"""`connect --write`: asks first, prints only the new entry, keeps the rest of the file."""

import argparse
import json
import tomllib
from pathlib import Path

import pytest

from incognito_sql.connect.clients import http
from incognito_sql.connect.run import Where, add_connect_parser, run_connect
from incognito_sql.connect.write import WriteRefused, default_file, read, updated
from incognito_sql.demo import DSN_ENV, run_demo

URL = "http://127.0.0.1:8766/mcp"
SECRET = "ghp_NotARealToken_123"  # noqa: S105 -- another server's secret, invented
TOKEN = "f3a9c0d2b7e14c6a8d5f0b1e2c3a4d5e"  # noqa: S105 -- a token's shape, invented


@pytest.fixture
def config(tmp_path: Path) -> Path:
    assert run_demo(tmp_path / "demo") == 0
    return tmp_path / "demo" / "shop.yaml"


def _run(tmp: Path, *argv: str, terminal: bool = True, answer: str = "y") -> int:
    parser = argparse.ArgumentParser()
    add_connect_parser(parser.add_subparsers(dest="command"))
    where = Where(tmp, tmp, None, terminal, lambda _: answer)
    return run_connect(parser.parse_args(["connect", *argv]), where)


def test_json_keeps_other_servers_text_and_refuses_what_it_cannot_merge() -> None:
    server = http("shop", URL)
    before = json.dumps({"name": "שלום", "mcpServers": {"other": {"url": "x"}}})
    after = updated("cursor", server, before)
    assert "שלום" in after
    assert not after.endswith("\n")  # the file had no final newline
    assert set(json.loads(after)["mcpServers"]) == {"other", "shop"}
    with pytest.raises(WriteRefused, match="already there"):
        updated("cursor", server, after)
    with pytest.raises(WriteRefused, match="not plain JSON"):
        updated("opencode", server, '{ // a comment\n "mcp": {} }')


@pytest.mark.parametrize(
    ("before", "reason"),
    [
        ('mcp_servers = { other = { url = "x" } }\n', "cannot be appended"),
        ("mcp_servers = 3\n", "not a table"),
        ('mcp_servers = "shopping"\n', "not a table"),
        ("model = ", "not valid TOML"),
    ],
)
def test_toml_refuses_a_layout_it_would_break(before: str, reason: str) -> None:
    with pytest.raises(WriteRefused, match=reason):
        updated("codex", http("shop", URL), before)


def test_toml_gains_a_table_and_nothing_else_changes() -> None:
    before = '# mine\nmodel = "x"\n'
    after = updated("codex", http("shop", URL), before)
    assert after.startswith(before)
    assert tomllib.loads(after)["mcp_servers"]["shop"]["url"] == URL


def test_files_are_read_as_utf8_with_or_without_a_bom(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_bytes(b'\xef\xbb\xbf{"mcpServers": {}}')
    assert json.loads(read(path)) == {"mcpServers": {}}
    path.write_text('{"mcpServers": {}}', encoding="utf-16")
    with pytest.raises(WriteRefused, match="not UTF-8"):
        read(path)
    assert read(tmp_path / "none.json") == ""


def test_codex_home_moves_codex_s_file(tmp_path: Path) -> None:
    assert default_file("codex", tmp_path, tmp_path, None) == tmp_path / ".codex" / "config.toml"
    assert default_file("codex", tmp_path, tmp_path, "/c") == Path("/c") / "config.toml"


def test_without_a_terminal_nothing_of_the_file_is_read_or_printed(
    config: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "opencode.json"
    settings.write_text(json.dumps({"mcp": {"gh": {"environment": {"T": SECRET}}}}), "utf-8")
    assert _run(tmp_path, "opencode", "--config", str(config), "--write", terminal=False) == 1
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    assert "no terminal" in out.err


def test_a_yes_adds_the_entry_and_prints_only_it(
    config: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "opencode.json"
    settings.write_text(json.dumps({"mcp": {"gh": {"environment": {"T": SECRET}}}}), "utf-8")
    assert _run(tmp_path, "opencode", "--config", str(config), "--write") == 0
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    written = json.loads(settings.read_text("utf-8"))
    assert written["mcp"]["gh"]["environment"] == {"T": SECRET}
    assert written["mcp"]["shop"]["environment"] == {DSN_ENV: f"{{env:{DSN_ENV}}}"}
    assert _run(tmp_path, "opencode", "--config", str(config), "--write") == 1  # name taken
    assert _run(tmp_path, "codex", "--config", str(config), "--write", answer="n") == 1


def test_a_value_where_a_name_belongs_is_refused_and_never_repeated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dsn = "postgresql://u:pw@h/db"
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        f"dsn_env: '{dsn}'\ndialect: sqlite\ncolumns:\n  t: {{id: open}}\n"
        "entities:\n  - {table: t, pk: id}\n",
        "utf-8",
    )
    assert _run(tmp_path, "cursor", "--config", str(bad)) == 2
    assert _run(tmp_path, "cursor", "--url", URL, "--token-env", TOKEN) == 2
    assert _run(tmp_path, "cursor", "--url", f"http://u:{TOKEN}@127.0.0.1:8766/mcp") == 2
    assert _run(tmp_path, "cursor", "--url", f"{URL}?token={TOKEN}") == 2
    out = capsys.readouterr()
    assert dsn not in out.out + out.err
    assert TOKEN not in out.out + out.err


def test_claude_code_is_not_written_and_bad_input_is_a_usage_error(
    config: Path, tmp_path: Path
) -> None:
    assert _run(tmp_path, "claude-code", "--config", str(config), "--write") == 2
    assert _run(tmp_path, "cursor", "--config", str(tmp_path / "missing.yaml")) == 2
    assert _run(tmp_path, "cursor", "--url", URL, "--name", "bad name") == 2
    assert _run(tmp_path, "cursor", "--url", URL) == 0


def test_a_settings_path_that_is_a_folder_is_a_failure_not_a_trace(
    config: Path, tmp_path: Path
) -> None:
    (tmp_path / "opencode.json").mkdir()
    assert _run(tmp_path, "opencode", "--config", str(config), "--write") == 1


# Nesting deeper than any platform's parser goes: Linux reads 5000 levels, Windows does not.
@pytest.mark.parametrize("text", ["[" * 10**6 + "]" * 10**6, '{"n": ' + "9" * 5000 + "}"])
def test_json_a_parser_cannot_read_is_refused(text: str) -> None:
    with pytest.raises(WriteRefused, match="not plain JSON"):
        updated("cursor", http("shop", URL), text)


def test_text_that_cannot_be_written_back_is_refused_before_the_file_is_touched() -> None:
    with pytest.raises(WriteRefused, match="cannot be written back"):
        updated("cursor", http("shop", URL), '{"mcpServers": {"x": {"note": "\ud800"}}}')


def test_a_number_that_would_come_back_as_infinity_is_refused() -> None:
    with pytest.raises(WriteRefused, match="number"):
        updated("cursor", http("shop", URL), '{"mcpServers": {}, "n": 1e400}')


def test_errors_never_name_the_settings_path(
    config: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "opencode.json").write_bytes(b"\xff\xfe{")
    assert _run(tmp_path, "opencode", "--config", str(config), "--write") == 1
    (tmp_path / "opencode.json").unlink()
    assert _run(tmp_path, "opencode", "--config", str(config), "--write", answer="n") == 1
    errors = [
        line
        for line in capsys.readouterr().err.splitlines()
        if "not UTF-8" in line or "left as it was" in line
    ]
    assert len(errors) == 2
    assert all(str(tmp_path) not in line for line in errors)  # the next steps may name it


def test_yes_writes_without_a_terminal_or_a_question(
    config: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "opencode.json"
    settings.write_text(json.dumps({"mcp": {"gh": {"environment": {"T": SECRET}}}}), "utf-8")
    argv = ("opencode", "--config", str(config), "--write")
    assert _run(tmp_path, *argv, terminal=False) == 1  # without --yes: refused, as before
    assert _run(tmp_path, *argv, "--yes", terminal=False, answer="n") == 0  # never asked
    assert set(json.loads(settings.read_text("utf-8"))["mcp"]) == {"gh", "shop"}
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    assert "[y/N]" not in out.out + out.err


def test_yes_is_only_for_write(config: Path, tmp_path: Path) -> None:
    assert _run(tmp_path, "opencode", "--config", str(config), "--yes") == 2


@pytest.mark.parametrize("client", ["claude-code", "codex", "cursor", "opencode"])
def test_an_env_file_entry_runs_serve_with_it_and_passes_no_dsn(
    config: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], client: str
) -> None:
    env = tmp_path / "secrets.env"
    assert _run(tmp_path, client, "--config", str(config), "--env-file", str(env)) == 0
    out = capsys.readouterr()
    assert "--env-file" in out.out
    assert str(env.resolve()) in out.out or str(env.resolve()).replace("\\", "\\\\") in out.out
    assert DSN_ENV not in out.out  # the server reads it from the file, not the entry
    assert "reads its DSN from the --env-file" in out.err


def test_an_env_file_goes_only_with_a_config(tmp_path: Path) -> None:
    assert _run(tmp_path, "codex", "--url", URL, "--env-file", "x.env") == 2


@pytest.mark.parametrize("client", ["claude-code", "codex", "cursor", "opencode"])
def test_a_service_entry_names_the_token_variable_not_the_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, client: str
) -> None:
    monkeypatch.setenv("INCOGNITO_SQL_MCP_TOKEN", TOKEN)
    assert _run(tmp_path, client, "--url", URL) == 0
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
    assert "INCOGNITO_SQL_MCP_TOKEN" in out.out


def test_a_path_from_codex_home_is_named_not_printed(
    config: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "Zqcanary-home"
    parser = argparse.ArgumentParser()
    add_connect_parser(parser.add_subparsers(dest="command"))
    asked: list[str] = []

    def answer(question: str) -> str:
        asked.append(question)
        return "y"

    where = Where(tmp_path, tmp_path, str(home), terminal=True, ask=answer)
    args = parser.parse_args(["connect", "codex", "--config", str(config), "--write"])
    assert run_connect(args, where) == 0
    assert (home / "config.toml").exists()
    out = capsys.readouterr()
    for text in (*asked, out.out, out.err):
        assert "zqcanary" not in text.lower()
    assert "the Codex config (from CODEX_HOME)" in asked[0]
    assert "added demo to the Codex config (from CODEX_HOME)" in out.err.replace("shop", "demo")
