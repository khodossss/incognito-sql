"""Stage A of the harness probe: the clients' isolation, their server lists, the verdict."""

import json
import subprocess
from pathlib import Path

import pytest

from bench.client import connect
from bench.client.clients import Client, find, state
from bench.client.connect import DSN_ENV, main, probe


def test_a_server_list_line_says_connected_failed_or_listed() -> None:
    claude = "probe1: python -m incognito_sql serve - ✔ Connected\nother: x - ✘ Failed to connect"
    assert state(claude, "probe1") == "connected"
    assert state(claude, "other") == "failed"
    assert state("✗ probe1 failed\n  MCP error -32000", "probe1") == "failed"
    assert state("Name     Command\nprobe1   python", "probe1") == "listed"
    assert state("probe12 connected", "probe1") == "absent"


def test_each_client_reads_its_settings_from_the_probe_folder(tmp_path: Path) -> None:
    env = Client("claude-code", None, connects=True).isolated(tmp_path)
    settings = Path(env["CLAUDE_CONFIG_DIR"]) / "settings.json"
    assert json.loads(settings.read_text(encoding="utf-8")) == {"enableAllProjectMcpServers": True}
    xdg = Client("opencode", None, connects=True).isolated(tmp_path)
    assert sorted(xdg) == ["XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"]
    assert all(value.startswith(str(tmp_path)) for value in xdg.values())
    assert Client("codex", None, connects=False).isolated(tmp_path) == {
        "CODEX_HOME": str(tmp_path / "codex-home")
    }


def test_claude_code_is_found_in_the_newest_vs_code_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("bench.client.clients.shutil.which", lambda _name: None)
    for version in ("2.1.9", "2.1.314"):
        folder = tmp_path / ".vscode/extensions" / f"anthropic.claude-code-{version}-win32-x64"
        binary = folder / "resources/native-binary/claude.exe"
        binary.parent.mkdir(parents=True)
        binary.touch()
    claude = find(tmp_path)[0]
    assert claude.binary is not None
    assert "2.1.314" in str(claude.binary)
    assert [c.binary for c in find(tmp_path)[1:]] == [None, None]


class FakeClient:
    """Answers the probe's commands; the server list shows the server while the DSN is set."""

    def __init__(self, *, leak_to: Path | None = None) -> None:
        self.calls: list[list[str]] = []
        self.leak_to = leak_to

    def __call__(self, argv: list[str], **kw: object) -> "subprocess.CompletedProcess[str]":
        self.calls.append(argv)
        env = kw["env"]
        assert isinstance(env, dict)
        out = ""
        if "--name" in argv:
            self.server = argv[argv.index("--name") + 1]
            out = f"claude mcp add --scope project {self.server} -- python\n"
            if self.leak_to is not None:
                self.leak_to.write_text(self.server, encoding="utf-8")
        if argv[-2:] == ["mcp", "list"]:
            out = f"{self.server}: ✔ Connected" if DSN_ENV in env else f"{self.server}: ✘ Failed"
        return subprocess.CompletedProcess(argv, 0, out, "")


def test_a_client_that_takes_the_entry_passes(tmp_path: Path) -> None:
    fake = FakeClient()
    opencode = Client("opencode", tmp_path / "opencode.exe", connects=True)
    outcome = probe(opencode, tmp_path / "run", tmp_path / "home", fake)
    assert (outcome.with_dsn, outcome.without_dsn, outcome.failed) == ("connected", "failed", "")
    assert outcome.passed(connects=True)
    assert any(c[-2:] == ["--write", "--yes"] for c in fake.calls)  # no terminal to answer


def test_claude_code_runs_the_command_connect_prints(tmp_path: Path) -> None:
    fake = FakeClient()
    claude = Client("claude-code", tmp_path / "bin" / "claude.exe", connects=True)
    assert probe(claude, tmp_path / "run", tmp_path / "home", fake).passed(connects=True)
    shell = next(c for c in fake.calls if c[0] in {"powershell.exe", "sh"})
    assert shell[-1].startswith("claude mcp add --scope project probe")


def test_the_probe_fails_when_the_owners_settings_mention_its_server(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    fake = FakeClient(leak_to=home / ".codex" / "config.toml")
    codex = Client("codex", tmp_path / "codex.exe", connects=False)
    outcome = probe(codex, tmp_path / "run", home, fake)
    assert outcome.with_dsn == "connected"
    assert not outcome.owner_untouched
    assert not outcome.passed(connects=False)


def test_a_command_that_fails_is_reported_not_raised(tmp_path: Path) -> None:
    def failing(argv: list[str], **_: object) -> "subprocess.CompletedProcess[str]":
        return subprocess.CompletedProcess(argv, 2, "", "error: arguments: not accepted")

    outcome = probe(
        Client("opencode", tmp_path / "o.exe", connects=True), tmp_path, tmp_path, failing
    )
    assert "exited 2" in outcome.failed
    assert not outcome.passed(connects=True)
    assert (
        probe(Client("codex", None, connects=False), tmp_path, tmp_path).failed == "not installed"
    )


def test_main_prints_a_line_per_client_and_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(connect, "find", lambda _home, _claude: [])
    assert main([]) == 2
    opencode = Client("opencode", tmp_path / "o.exe", connects=True)
    monkeypatch.setattr(connect, "find", lambda _home, _claude: [opencode])
    assert main([], FakeClient()) == 0
    assert "opencode: pass; with the DSN connected, without it failed" in capsys.readouterr().out
