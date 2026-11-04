"""Several databases in several projects, and a change to a declaration already in use."""

import shutil
from pathlib import Path

from incognito_sql.setup.common import RESTART
from incognito_sql.setup.model import Answers, Case, Kind, Question, Step, Who, fill
from incognito_sql.setup.widen import put_back_unless_confirmed, widenings


def _widened(answers: Answers) -> list[str]:
    return widenings(Path(fill("{before}", answers)), Path(fill("{config}", answers)))


def _keep_before(answers: Answers) -> None:
    shutil.copyfile(fill("{config}", answers), fill("{before}", answers))


PROJECTS = Case(
    "projects",
    "different databases in different projects, each with its own entry",
    (
        Step(
            "each",
            Who.AGENT,
            "Run the case `own` in each project's folder (`incognito-sql guide --case own`), "
            "with a name, a variable and an entry of its own: the entry goes to the project "
            "(Claude Code's .mcp.json, OpenCode's opencode.json). Codex keeps one "
            "~/.codex/config.toml: there each database is one entry with its own --name "
            "(not tried with Codex).",
        ),
        Step(
            "ports",
            Who.AGENT,
            "Give each config its own cards' port (8765, 8767, ...): two servers cannot "
            "share it. Repeat for each project's config.",
            ask=Question("port", "The cards' port of this config?", Kind.TEXT, default="8767"),
            run=("set", "{config}", "web_port", "{port}"),
            writes=("{config}",),
        ),
    ),
)

CHANGE = Case(
    "change",
    "a declaration already in use changes: the human confirms anything it opens",
    (
        Step(
            "config",
            Who.AGENT,
            "The config that changes.",
            ask=Question("config", "Path of the config?", Kind.PATH),
        ),
        Step(
            "before",
            Who.AGENT,
            "Copy {config} to {before} before touching it.",
            writes=("{before}",),
            act=_keep_before,
        ),
        Step(
            "edit",
            Who.AGENT,
            "Change {config} as wanted. Once any table has a rule on rows, every open view, "
            "and every table that shares rows with a ruled one by inheritance (partitions, "
            "child tables) but lacks its rules, must be listed under `verified_relations`, "
            "after the human checks that it shows no row the rules hide; otherwise the "
            "server does not start.",
            writes=("{config}",),
        ),
        Step(
            "diff",
            Who.AGENT,
            "Compare: each line says what the model would see more (WIDENED), less "
            "(NARROWED) or otherwise.",
            run=("diff", "{before}", "{config}", "--ci"),
        ),
        Step(
            "confirm",
            Who.HUMAN,
            "The human confirms each WIDENED line on its own; unless every one is confirmed, "
            "{config} is put back from {before}.",
            ask=Question(
                "widened",
                "Open what each WIDENED line opens?",
                Kind.YESNO,
                options=_widened,
                hint="one question per WIDENED line of the diff",
            ),
            writes=("{config}",),
            act=put_back_unless_confirmed,
        ),
        RESTART,
        Step(
            "check",
            Who.AGENT,
            "Check the installation still is what it was.",
            run=("check", "--config", "{config}"),
        ),
    ),
)
