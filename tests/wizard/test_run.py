"""The `setup` command: a terminal or nothing, the case asked, the exit code."""

import pytest

from incognito_sql.wizard.prompts import LinePrompter
from incognito_sql.wizard.run import run_setup

from .conftest import Calls, Script


def _run(script: Script, name: str | None, start: str | None = None, *, terminal: bool) -> int:
    return run_setup(name, start, terminal=terminal, prompter=script.terminal, call=Calls())


def test_without_a_terminal_it_refuses_before_any_question(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = Script()
    assert _run(script, None, terminal=False) == 2
    assert script.shown == []
    assert "incognito-sql guide" in capsys.readouterr().err


@pytest.mark.parametrize(("name", "start"), [(None, "demo"), ("demo", "nowhere")])
def test_a_wrong_from_is_refused(name: str | None, start: str) -> None:
    script = Script()
    assert _run(script, name, start, terminal=True) == 2
    assert script.shown == []


def test_the_case_is_asked_when_not_named() -> None:
    script = Script("demo", "1", "", "", "", "", "")
    assert _run(script, None, terminal=True) == 0
    assert "own: your own database" in script.text()
    assert "The setup is done." in script.text()


def test_a_stop_is_the_exit_code() -> None:
    script = Script("1", "", "n")  # client, folder, then "no" to demo-dsn's "Done?"
    assert _run(script, "demo", terminal=True) == 1


@pytest.mark.parametrize("stop", [KeyboardInterrupt, EOFError])
def test_ctrl_c_or_a_closed_input_stops_with_130(
    stop: type[BaseException], capsys: pytest.CaptureFixture[str]
) -> None:
    def gone(_prompt: str) -> str:
        raise stop

    ask = LinePrompter(gone, lambda _: None)
    assert run_setup("demo", None, terminal=True, prompter=lambda: ask, call=Calls()) == 130
    assert "setup stopped" in capsys.readouterr().err
