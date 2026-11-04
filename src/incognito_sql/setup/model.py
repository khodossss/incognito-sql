"""The setup's steps as data: a case is a list of steps, each a question, a command, a doer.

Two faces read the same data: `guide` prints it for an agent, the wizard walks a human
through it in a terminal. Neither holds steps of its own.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

Answers = dict[str, str | list[str]]  # never a secret: a secret step keeps only its NAME


class Who(StrEnum):
    """Who does a step."""

    AGENT = "agent"
    HUMAN = "human"  # in the human's own terminal or client, never through the chat
    ADMIN = "admin"  # the human, as an administrator


class Kind(StrEnum):
    """What answer a question takes."""

    CHOICE = "choice"
    YESNO = "yesno"
    TEXT = "text"
    PATH = "path"
    COLUMNS = "columns"  # a class for each column of the scaffold
    NONE = "none"  # an action only: the doer says when it is done


Options = tuple[str, ...] | Callable[[Answers], Sequence[str]]


@dataclass(frozen=True)
class Question:
    """What a step asks; ``hint`` says in words where callable options come from."""

    id: str
    text: str
    kind: Kind
    options: Options | None = None
    default: str | None = None
    hint: str = ""
    valid: Callable[[str], bool] | None = None  # an answer it refuses is asked again

    def choices(self, answers: Answers) -> Sequence[str]:
        """Return the options given the answers so far."""
        if self.options is None:
            return ()
        return self.options(answers) if callable(self.options) else self.options


@dataclass(frozen=True)
class Step:
    """One step: who does it, what is said or asked, and the command of this CLI it runs.

    ``run`` is the argv of an `incognito-sql` command, its words templates over the
    answers (``{client}``); a step outside this CLI (an OS account, a restart) has none
    and says what to do; its ``act``, if any, does it in process for the wizard (the agent
    follows ``say``). ``when`` skips the step unless it holds for the answers.
    """

    id: str
    who: Who
    say: str
    ask: Question | None = None
    run: tuple[str, ...] | None = None
    writes: tuple[str, ...] = ()
    done: str = ""
    when: Callable[[Answers], bool] | None = None
    only: str = ""  # ``when`` in words, for the guide
    act: Callable[[Answers], None] | None = None  # what it does in process with no command

    def applies(self, answers: Answers) -> bool:
        """Tell whether the step runs for these answers."""
        return self.when is None or self.when(answers)


@dataclass(frozen=True)
class Case:
    """A way to set the server up: its name, when to choose it, and its steps."""

    name: str
    choose_when: str
    steps: tuple[Step, ...]


SCHEMES = {"postgres": "postgresql+psycopg", "mysql": "mysql+pymysql", "tsql": "mssql+pymssql"}
FILE_DIALECTS = ("sqlite", "duckdb")


def _derived(values: dict[str, str]) -> dict[str, str]:
    """Return the slots the answers imply: the DSN's scheme, the config's path."""
    out: dict[str, str] = {}
    if values.get("dialect") in SCHEMES:
        out["scheme"] = SCHEMES[values["dialect"]]
    if "folder" in values and "name" in values:
        out["config"] = f"{values['folder']}/{values['name']}.yaml"
    if "config" in values or "config" in out:
        config = values.get("config") or out["config"]
        out["before"] = config.removesuffix(".yaml") + ".before.yaml"
    return out


class _Fill(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return f"<{key}>"  # not answered yet: the guide shows the slot


def fill(text: str, answers: Answers) -> str:
    """Fill ``{name}`` slots from the answers; an unanswered slot stays ``<name>``."""
    values = {k: " ".join(v) if isinstance(v, list) else v for k, v in answers.items()}
    return text.format_map(_Fill({**_derived(values), **values}))


def render(step: Step, answers: Answers) -> list[str] | None:
    """Return the step's argv for these answers, or None for a step outside this CLI."""
    if step.run is None:
        return None
    return [fill(word, answers) for word in step.run]
