"""Arrow-key prompts with real keys through a pipe, and the fall back to numbers."""

from collections.abc import Iterator

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import PipeInput
from prompt_toolkit.output import DummyOutput

from incognito_sql.wizard import arrows
from incognito_sql.wizard.arrows import NO_ARROWS, ArrowPrompter, arrows_work
from incognito_sql.wizard.prompts import LinePrompter

DOWN, ENTER, SPACE = "\x1b[B", "\r", " "
OPTIONS = ("claude-code", "codex", "opencode")


@pytest.fixture
def keys() -> Iterator[PipeInput]:
    with create_pipe_input() as pipe:
        yield pipe


def _prompter(keys: PipeInput, typed: str) -> tuple[ArrowPrompter, list[str]]:
    keys.send_text(typed)
    shown: list[str] = []
    return ArrowPrompter(shown.append, input=keys, output=DummyOutput()), shown


def test_one_moves_with_the_arrows(keys: PipeInput) -> None:
    ask, _ = _prompter(keys, DOWN + ENTER)
    assert ask.one("Client?", OPTIONS, None) == "codex"


def test_one_starts_on_the_default(keys: PipeInput) -> None:
    ask, _ = _prompter(keys, ENTER)
    assert ask.one("Client?", OPTIONS, "opencode") == "opencode"


def test_many_ticks_with_the_space_bar(keys: PipeInput) -> None:
    ask, _ = _prompter(keys, SPACE + DOWN + DOWN + SPACE + ENTER)  # untick 1, tick 3
    assert ask.many("Which?", OPTIONS, ["claude-code"]) == ["opencode"]


@pytest.mark.parametrize(("typed", "answer"), [("y", True), ("n", False), (ENTER, True)])
def test_yesno(keys: PipeInput, typed: str, *, answer: bool) -> None:
    ask, _ = _prompter(keys, typed)
    assert ask.yesno("Go on?", default=True) is answer


def test_text_takes_only_what_is_valid(keys: PipeInput) -> None:
    ask, _ = _prompter(keys, "shop" + ENTER + "\x7f" * 4 + "SHOP" + ENTER)
    assert ask.text("Variable?", None, str.isupper) == "SHOP"


def test_text_takes_the_default(keys: PipeInput) -> None:
    ask, _ = _prompter(keys, ENTER)
    assert ask.text("Folder?", ".", None) == "."


def test_tell_writes_a_line(keys: PipeInput) -> None:
    ask, shown = _prompter(keys, "")
    ask.tell("Cases:")
    assert shown == ["Cases:\n"]


def _no_console() -> object:
    raise OSError  # stands in for NoConsoleScreenBufferError


@pytest.mark.parametrize(
    ("terminal", "console", "works"),
    [(True, object, True), (False, object, False), (True, _no_console, False)],
)
def test_arrows_work_only_in_a_console(*, terminal: bool, console: object, works: bool) -> None:
    assert arrows_work(output_is_terminal=terminal, open_console=console) is works  # type: ignore[arg-type]


def test_no_console_falls_back_to_numbers_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(arrows, "create_output", _no_console)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert isinstance(arrows.prompter(), LinePrompter)
    assert NO_ARROWS in capsys.readouterr().out


def test_a_console_gets_the_arrows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arrows, "create_output", object)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert isinstance(arrows.prompter(), ArrowPrompter)
