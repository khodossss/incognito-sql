"""Stage A of the harness probe: each client connects to the demo shop through `connect`.

    uv run python -m bench.client.connect

No model and no sign-in: in a temporary folder, `demo` writes the shop, `connect` writes
each client's entry (Claude Code runs the command `connect` prints, as a person would),
and the client's own server list must show the server connected with the DSN set and
failing without it. The owner's own settings must not mention the probe's server. Exit 0
when every installed client passes, 1 when one fails, 2 when none is installed.
"""

import argparse
import base64
import os
import secrets
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from bench.client.clients import Client, find, state

DSN_ENV = "DEMO_SHOP_DSN"
KEY_ENV = "INCOGNITO_SQL_KEY"
TIMEOUT_S = 180
# connect quotes for PowerShell on Windows, for a POSIX shell elsewhere.
_SHELL = ["powershell.exe", "-NoProfile", "-Command"] if os.name == "nt" else ["sh", "-c"]
Run = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass
class Outcome:
    """What one client showed: with the DSN, without it, and the owner's files."""

    client: str
    with_dsn: str = ""
    without_dsn: str = ""
    owner_untouched: bool = True
    failed: str = ""

    def passed(self, *, connects: bool) -> bool:
        """Tell whether the client took the entry and the owner's settings stayed as is."""
        good = ("connected",) if connects else ("connected", "listed")
        refused = self.without_dsn == "failed" or not connects
        return not self.failed and self.with_dsn in good and refused and self.owner_untouched


def probe(client: Client, root: Path, home: Path, run: Run = subprocess.run) -> Outcome:
    """Connect ``client`` to a fresh demo shop under ``root``; never raise."""
    outcome = Outcome(client.name)
    server = f"probe{secrets.token_hex(4)}"
    binary = client.binary
    if binary is None:
        outcome.failed = "not installed"
        return outcome
    try:
        env = _environment(client, root)
        project = root / "project"
        project.mkdir(parents=True)
        _incognito(run, ["demo", str(root / "demo")], env, root)
        config = str(root / "demo" / "shop.yaml")
        entry = ["connect", client.name, "--config", config, "--name", server]
        if client.name == "claude-code":  # it writes its own settings: run what connect prints
            printed = _incognito(run, entry, env, project).strip().splitlines()[0]
            env["PATH"] = f"{binary.parent}{os.pathsep}{env.get('PATH', '')}"
            _call(run, [*_SHELL, printed], env, project)
        else:
            _incognito(run, [*entry, "--write", "--yes"], env, project)
        listing = [str(binary), "mcp", "list"]
        outcome.with_dsn = state(_call(run, listing, env, project), server)
        env.pop(DSN_ENV)
        outcome.without_dsn = state(_call(run, listing, env, project, check=False), server)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        outcome.failed = f"{type(exc).__name__}: {exc}"
    outcome.owner_untouched = not any(
        server in path.read_text(encoding="utf-8", errors="replace")
        for path in client.owner_files(home)
        if path.is_file()
    )
    return outcome


def _environment(client: Client, root: Path) -> dict[str, str]:
    env = {**os.environ, **client.isolated(root)}
    env[KEY_ENV] = base64.b64encode(secrets.token_bytes(32)).decode()
    env[DSN_ENV] = f"sqlite:///{(root / 'demo' / 'shop.db').resolve().as_posix()}"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _incognito(run: Run, args: list[str], env: dict[str, str], cwd: Path) -> str:
    return _call(run, [sys.executable, "-m", "incognito_sql", *args], env, cwd)


def _call(run: Run, argv: list[str], env: dict[str, str], cwd: Path, *, check: bool = True) -> str:
    done = run(
        argv, cwd=cwd, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=TIMEOUT_S, check=False,
    )  # fmt: skip
    if check and done.returncode != 0:
        what = " ".join([Path(argv[0]).name, *argv[1:3]])
        msg = f"{what} exited {done.returncode}: {done.stderr.strip()[-300:]}"
        raise RuntimeError(msg)
    return done.stdout + done.stderr


def main(argv: Sequence[str] | None = None, run: Run = subprocess.run) -> int:
    """Probe every installed client; print a line each and the verdict."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--claude", type=Path, help="Claude Code's binary (default: PATH, then VS Code)"
    )
    args = parser.parse_args(argv)
    home = Path.home()
    clients = [c for c in find(home, args.claude) if c.binary is not None]
    if not clients:
        sys.stderr.write("no client installed: claude, opencode or codex\n")
        return 2
    passed = True
    for client in clients:
        with tempfile.TemporaryDirectory(prefix="incognito-probe-") as tmp:
            outcome = probe(client, Path(tmp), home, run)
        ok = outcome.passed(connects=client.connects)
        passed &= ok
        sys.stdout.write(
            f"{client.name}: {'pass' if ok else 'FAIL'}; with the DSN {outcome.with_dsn or '-'}, "
            f"without it {outcome.without_dsn or '-'}, owner's settings "
            f"{'untouched' if outcome.owner_untouched else 'CHANGED'}"
            f"{'; ' + outcome.failed if outcome.failed else ''}\n"
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
