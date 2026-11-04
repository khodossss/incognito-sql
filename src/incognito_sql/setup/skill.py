"""`incognito-sql skill`: a skill that tells a client's agent how to start the setup.

Claude Code, Codex and OpenCode read the same SKILL.md: a name, a description that says
when to use it, and the text. The skill only says how to begin (run `guide` of this
version) and the rule on secrets; the steps themselves stay in `guide`. It is written
as `connect --write` writes: after a yes on a terminal, or with `--yes`; a folder built
from an environment variable is named by the variable, not printed; a skill already
there with other text is replaced only after that yes.
"""

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from incognito_sql.connect.release import release
from incognito_sql.setup.guide import RULE

if TYPE_CHECKING:
    import argparse

EXIT_FAILED = 1
EXIT_USAGE = 2
NAME = "incognito-sql"
# The client, the variable that moves its config folder, the folder under the home
# without it, and the skills folder under that.
_FOLDERS = {
    "claude-code": ("CLAUDE_CONFIG_DIR", Path(".claude"), Path("skills")),
    "codex": ("CODEX_HOME", Path(".codex"), Path("skills")),
    "opencode": ("XDG_CONFIG_HOME", Path(".config"), Path("opencode", "skill")),
}
CLIENTS = tuple(_FOLDERS)


@dataclass(frozen=True)
class Place:
    """What `skill` reads besides its arguments: the home, the environment, the terminal."""

    home: Path
    env: Mapping[str, str]
    terminal: bool
    ask: Callable[[str], str]
    version: str | None  # the published release installed, None for a checkout

    @classmethod
    def here(cls) -> "Place":
        """Return this process's place."""
        return cls(Path.home(), os.environ, sys.stdin.isatty(), input, release())


def add_skill_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `skill` subcommand."""
    cmd = commands.add_parser("skill", help="give a client's agent the skill to start the setup")
    cmd.add_argument("client", choices=CLIENTS)
    cmd.add_argument("--yes", action="store_true", help="write without asking, no terminal needed")


def run_skill(args: "argparse.Namespace", place: Place) -> int:
    """Write the skill into the client's skills folder after a yes."""
    path, shown = folder(args.client, place.home, place.env)
    path /= NAME
    shown = f"{shown}{os.sep}{NAME}"
    after = text(place.version)
    try:
        before = (path / "SKILL.md").read_text(encoding="utf-8")
    except FileNotFoundError:
        before = None
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(f"cannot read the skill there: {type(exc).__name__}", EXIT_FAILED)
    if before == after:
        sys.stderr.write(f"incognito-sql: the skill in {shown} is already this one\n")
        return 0
    if not (args.yes or place.terminal):
        return _fail(
            "skill asks before it writes, and there is no terminal: add --yes", EXIT_FAILED
        )
    verb = "Write" if before is None else "Replace the skill there, whose text differs, with"
    question = f"{verb} the incognito-sql skill in {shown}? [y/N] "
    if not args.yes and not _yes(place.ask, question):
        return _fail("nothing was written", EXIT_FAILED)
    try:
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(after, encoding="utf-8", newline="\n")
    except OSError as exc:
        return _fail(f"cannot write the skill: {type(exc).__name__}", EXIT_FAILED)
    done = "wrote" if before is None else "replaced"
    sys.stderr.write(f"incognito-sql: {done} the skill in {shown}; restart the client\n")
    if place.version is None:
        sys.stderr.write(
            "incognito-sql: this installation is no published release: the skill runs "
            "`incognito-sql` as found on the client's PATH\n"
        )
    return 0


def folder(client: str, home: Path, env: Mapping[str, str]) -> tuple[Path, str]:
    """Return the client's skills folder and how to name it: by its variable if one moved it."""
    variable, default, skills = _FOLDERS[client]
    moved = env.get(variable)
    if moved:  # a path from the environment may hold anything pasted there: never printed
        return Path(moved) / skills, f"the {client} skills folder (from {variable})"
    path = home / default / skills
    return path, str(path)


def text(version: str | None) -> str:
    """Return the skill: when to use it, how to start the setup, the rule on secrets."""
    run = f'uvx "incognito-sql=={version}"' if version else "incognito-sql"
    return f"""---
name: {NAME}
description: Set up incognito-sql, the MCP server through which an agent queries a \
database holding personal data without receiving the values. Use when the user asks to \
connect a database through incognito-sql, to try its demo, to hide personal data from the \
agent while it writes SQL, or to change what an incognito-sql declaration hides.
---

# Setting up incognito-sql

1. Run `{run} guide`. It prints the setup's steps for this version: the cases (the demo,
   the user's own database, other people's data, several projects, a change to a
   declaration in use) and, for each step, who does it, what to ask and what to run.
2. Ask the user which case is theirs, unless they already said, then walk them through
   that case's steps in order: `{run} guide --case <case>`.
3. Every command the guide prints as `incognito-sql …` runs as `{run} …`.
4. A step marked for the human is theirs: tell them what to run in their own terminal
   and wait until they say it is done.
5. After the client restarts, go on with `{run} guide --case <case> --from <step>`.
6. Once the server is connected, query the database only through its tools, never the
   database file or a driver of your own.

{RULE}"""


def _yes(ask: Callable[[str], str], question: str) -> bool:
    try:
        answer = ask(question)
    except EOFError:  # Windows reads NUL as a terminal that answers nothing
        answer = ""
    return answer.strip().casefold() in {"y", "yes"}


def _fail(message: str, code: int) -> int:
    sys.stderr.write(f"incognito-sql: {message}\n")
    return code
