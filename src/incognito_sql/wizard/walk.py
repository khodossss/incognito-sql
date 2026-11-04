"""Walking one case's steps with a human: ask, run this CLI's command in process, or wait."""

from collections.abc import Callable
from pathlib import Path

from incognito_sql import shell
from incognito_sql.setup.model import Answers, Case, Kind, Question, Step, Who, fill, render
from incognito_sql.setup.widen import YES
from incognito_sql.wizard.columns import NotWritten, decide
from incognito_sql.wizard.prompts import Prompter

Call = Callable[[list[str]], int]  # `incognito_sql.cli.main`
# Answers a step before `--from` still asks: they fill the slots of the steps after it.
_SLOTS = (Kind.CHOICE, Kind.TEXT, Kind.PATH, Kind.YESNO)


class Stopped(Exception):  # noqa: N818 -- the human stopped the walk: said as is
    """The walk ends here; ``code`` is the process exit code."""

    def __init__(self, code: int) -> None:
        """Remember the exit code."""
        super().__init__(code)
        self.code = code


def walk(case: Case, prompter: Prompter, call: Call, start: str | None = None) -> Answers:
    """Walk ``case`` from ``start`` (or its first step); return the answers.

    Steps before ``start`` only ask what fills later commands; they run nothing.
    Raises ``Stopped`` when a step fails or the human does not go on.
    """
    answers: Answers = {}
    reached = start is None
    for step in case.steps:
        reached = reached or step.id == start
        if not step.applies(answers):
            continue
        if reached:
            prompter.tell(f"\n[{step.id}] {fill(step.say, answers)}")
        if step.ask is not None and (reached or step.ask.kind in _SLOTS):
            _answer(step.ask, answers, prompter)
        if not reached:
            continue
        try:
            _do(step, answers, prompter, call)
        except Stopped:
            resume = f"incognito-sql setup --case {case.name} --from {step.id}"
            prompter.tell(f"Stopped. Go on later with: {resume}")
            raise
    return answers


def _answer(question: Question, answers: Answers, prompter: Prompter) -> None:
    options = question.choices(answers)
    kind = question.kind
    if kind is Kind.CHOICE:
        answers[question.id] = prompter.one(question.text, options, question.default)
    elif kind is Kind.YESNO and options:  # one answer per option, e.g. per WIDENED line
        said: list[str] = []
        for option in options:
            prompter.tell(f"  {option}")
            said.append(_yesno(question.text, question, prompter))
        answers[question.id] = said
    elif kind is Kind.YESNO:
        answers[question.id] = _yesno(question.text, question, prompter)
    elif kind in (Kind.TEXT, Kind.PATH):
        answers[question.id] = prompter.text(question.text, question.default, question.valid)


def _yesno(text: str, question: Question, prompter: Prompter) -> str:
    return YES if prompter.yesno(text, default=question.default == YES) else "no"


def _do(step: Step, answers: Answers, prompter: Prompter, call: Call) -> None:
    argv = render(step, answers)
    try:
        if step.ask is not None and step.ask.kind is Kind.COLUMNS:
            answers[step.ask.id] = decide(Path(fill("{config}", answers)), prompter)
            return
        if argv is None and step.act is not None:  # what the agent does by hand, in process
            step.act(answers)
            return
    except NotWritten:
        raise Stopped(1) from None
    except OSError as exc:  # a file the step reads is missing: its text may hold the path
        prompter.tell(f"The step could not read or write its file ({type(exc).__name__}).")
        _go_on(step, answers, prompter)
        return
    if argv is None:
        if _waits(step):
            _go_on(step, answers, prompter)
        return
    if step.who is Who.ADMIN:  # the wizard runs as the human, never as an administrator
        prompter.tell("In a terminal opened as administrator, run:")
        prompter.tell("  " + shell.join(["incognito-sql", *argv]))
        _go_on(step, answers, prompter)
        return
    prompter.tell("> " + shell.join(["incognito-sql", *argv]))
    code = _run(call, argv)
    if code != 0:
        prompter.tell(f"The command ended with code {code}.")
        _go_on(step, answers, prompter)


def _waits(step: Step) -> bool:
    """Whether a step without a command has something for the human to do."""
    kind = step.ask.kind if step.ask is not None else None
    return kind in (None, Kind.NONE) or bool(step.writes)


def _go_on(step: Step, answers: Answers, prompter: Prompter) -> None:
    if step.ask is not None and step.ask.kind is Kind.NONE:
        question = step.ask.text  # e.g. "Restarted the client?"
    else:
        question = f"Done ({fill(step.done, answers)})?" if step.done else "Done?"
    if not prompter.yesno(question, default=True):
        raise Stopped(1)


def _run(call: Call, argv: list[str]) -> int:
    try:
        return call(argv)
    except SystemExit as exc:  # argparse refuses the arguments by exiting
        return exc.code if isinstance(exc.code, int) else 2
