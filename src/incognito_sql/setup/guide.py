"""`incognito-sql guide`: the setup's steps as text, for an agent to walk a human through."""

import sys
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from incognito_sql import shell
from incognito_sql.setup.cases import CASES, case
from incognito_sql.setup.model import Case, Step, Who, fill, render

if TYPE_CHECKING:
    import argparse

EXIT_USAGE = 2
RULE = (
    "Rule: never ask the human, in the chat, for a password, a DSN that holds one, a key, a "
    "token or any value from the database. A step that needs a secret is the human's: "
    "they run `incognito-sql secret` in their own terminal, and you learn only the "
    "variable's name.\n"
)
_DOER = {
    Who.AGENT: "you",
    Who.HUMAN: "the human, in their own terminal or client (not you)",
    Who.ADMIN: "the human as an administrator (not you)",
}


def add_guide_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `guide` subcommand."""
    guide = commands.add_parser("guide", help="print the setup steps for an agent")
    guide.add_argument("--case", choices=[c.name for c in CASES], help="one case only")
    guide.add_argument("--from", dest="start", metavar="STEP", help="from this step (with --case)")


def run_guide(name: str | None, start: str | None) -> int:
    """Print the guide: every case, or one, or one from a step on."""
    if start is not None and name is None:
        return _fail("--from goes with --case")
    chosen = CASES if name is None else (case(name),)
    if start is not None and start not in (s.id for s in chosen[0].steps):
        return _fail("--from names no step of this case: see `incognito-sql guide --case`")
    sys.stdout.write(text(chosen, start))
    return 0


def text(cases: tuple[Case, ...], start: str | None = None) -> str:
    """Return the guide for these cases; ``start`` skips the steps before it."""
    out = [f"incognito-sql {_version()}: setup guide\n", RULE]
    if len(cases) > 1:
        out.append("Ask the human which case is theirs:\n")
        out.extend(f"  {c.name}: {c.choose_when}\n" for c in cases)
    for one in cases:
        out.append(f"\n== {one.name}: {one.choose_when}\n")
        steps = one.steps
        if start is not None:
            steps = steps[[s.id for s in steps].index(start) :]
        out.extend(_step(step) for step in steps)
    return "".join(out)


def _step(step: Step) -> str:
    lines = [f"\n[{step.id}] {_DOER[step.who]}" + (f", only {step.only}" if step.only else "")]
    lines.append(f"  {fill(step.say, {})}")
    if step.ask is not None:
        options = step.ask.options if isinstance(step.ask.options, tuple) else ()  # not read
        detail = ", ".join(options) if options else step.ask.hint or step.ask.kind.value
        default = f"; default {step.ask.default}" if step.ask.default else ""
        lines.append(f"  ask: {step.ask.text} ({detail}{default})")
    argv = render(step, {})
    if argv is not None:
        lines.append(f"  run: {shell.join(['incognito-sql', *argv])}")
    if step.writes:
        lines.append(f"  writes: {', '.join(fill(w, {}) for w in step.writes)}")
    if step.done:
        lines.append(f"  done when: {step.done}")
    return "\n".join(lines) + "\n"


def _version() -> str:
    try:
        return version("incognito-sql")
    except PackageNotFoundError:  # run from a tree that was never installed
        return "(not installed)"


def _fail(message: str) -> int:
    sys.stderr.write(f"incognito-sql: {message}\n")
    return EXIT_USAGE
