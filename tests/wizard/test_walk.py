"""Walking a case: answers fill the commands, which run in process; failures stop the walk."""

from pathlib import Path

import pytest

from incognito_sql.setup.cases import case
from incognito_sql.setup.model import Case, Kind, Question, Step, Who
from incognito_sql.wizard import columns
from incognito_sql.wizard.walk import Stopped, walk

from .conftest import Calls, Script
from .test_columns import SCAFFOLD


def test_the_demo_runs_its_commands_with_the_answers() -> None:
    # client, folder; then "done" for restart, probe and cards
    script, calls = Script("4", "C:/demo", "", "", "", ""), Calls()
    answers = walk(case("demo"), script.terminal(), calls)
    assert answers == {"client": "opencode", "folder": "C:/demo"}
    assert calls.argvs == [
        ["demo", "C:/demo"],
        ["env", "DEMO_SHOP_DSN", "--file", "C:/demo/shop.db"],
        ["connect", "opencode", "--config", "C:/demo/shop.yaml", "--write", "--yes"],
    ]
    assert "Restarted the client?" in script.text()


def test_from_a_step_asks_earlier_questions_but_runs_nothing_before_it() -> None:
    script, calls = Script("1", "", "", "", "", ""), Calls()
    walk(case("demo"), script.terminal(), calls, start="connect-claude")
    assert calls.argvs == [["connect", "claude-code", "--config", "incognito-demo/shop.yaml"]]
    assert "[demo]" not in script.text()


def test_a_failed_command_stops_on_a_no_and_says_how_to_go_on() -> None:
    script = Script("2", "", "n")
    with pytest.raises(Stopped) as stopped:
        walk(case("demo"), script.terminal(), Calls(code=1))
    assert stopped.value.code == 1
    assert "ended with code 1" in script.text()
    assert "incognito-sql setup --case demo --from demo" in script.text()


def test_a_failed_command_goes_on_after_a_yes() -> None:
    one = Case("t", "", (Step("check", Who.AGENT, "Check.", run=("check",), done="closed"),))
    script = Script("y")
    walk(one, script.terminal(), Calls(code=1))
    assert "Done (closed)?" in script.text()


def test_arguments_the_parser_refuses_count_as_a_failure() -> None:
    def refuse(_argv: list[str]) -> int:
        raise SystemExit(2)

    one = Case("t", "", (Step("bad", Who.AGENT, "Bad.", run=("init",)),))
    script = Script("n")
    with pytest.raises(Stopped):
        walk(one, script.terminal(), refuse)
    assert "ended with code 2" in script.text()


def test_an_administrator_s_command_is_shown_never_run() -> None:
    step = Step("key", Who.ADMIN, "Make the key.", run=("secret", "KEY", "--env-file", "s.env"))
    script, calls = Script(""), Calls()
    walk(Case("t", "", (step,)), script.terminal(), calls)
    assert calls.argvs == []
    assert "as administrator" in script.text()
    assert "incognito-sql secret KEY --env-file s.env" in script.text()


def test_a_question_only_step_waits_for_nothing() -> None:
    step = Step("name", Who.AGENT, "Ask.", ask=Question("name", "Name?", Kind.TEXT, default="shop"))
    script = Script("")
    assert walk(Case("t", "", (step,)), script.terminal(), Calls()) == {"name": "shop"}
    assert "Done" not in script.text()


def test_a_yes_or_no_answer_is_kept_as_words() -> None:
    step = Step("ok", Who.HUMAN, "Ask.", ask=Question("ok", "Open it?", Kind.YESNO, default="no"))
    assert walk(Case("t", "", (step,)), Script("y").terminal(), Calls()) == {"ok": "yes"}


def test_a_step_that_does_not_apply_is_skipped() -> None:
    step = Step("x", Who.AGENT, "X.", run=("check",), when=lambda _: False, only="never")
    calls = Calls()
    walk(Case("t", "", (step,)), Script().terminal(), calls)
    assert calls.argvs == []


def test_a_step_s_act_runs_in_process_instead_of_waiting() -> None:
    seen: list[str] = []
    step = Step("copy", Who.AGENT, "Copy.", act=lambda _: seen.append("copied"), writes=("x",))
    script = Script()
    walk(Case("t", "", (step,)), script.terminal(), Calls())
    assert seen == ["copied"]
    assert "Done" not in script.text()


def test_a_yes_or_no_per_option_is_kept_as_a_list() -> None:
    lines = ("WIDENED a", "WIDENED b")
    ask = Question("widened", "Open it?", Kind.YESNO, options=lines, default="no")
    step = Step("confirm", Who.HUMAN, "Confirm.", ask=ask)
    script = Script("y", "")
    assert walk(Case("t", "", (step,)), script.terminal(), Calls()) == {"widened": ["yes", "no"]}
    assert "WIDENED b" in script.text()


_CONFIG = Step("config", Who.AGENT, "Ask.", ask=Question("config", "Config?", Kind.PATH))


def test_the_columns_step_decides_the_config_its_answers_name(tmp_path: Path) -> None:
    config = tmp_path / "shop.yaml"
    config.write_text(SCAFFOLD, encoding="utf-8")
    ask = Question("columns", "Class of each column?", Kind.COLUMNS)
    step = Step("columns", Who.AGENT, "Decide.", ask=ask, writes=("{config}",))
    answers = walk(
        Case("t", "", (_CONFIG, step)), Script(str(config), "y", "y", "", "").terminal(), Calls()
    )
    assert "customers.full_name: identifier" in answers["columns"]


def test_columns_given_up_stop_the_walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "shop.yaml"
    config.write_text(SCAFFOLD, encoding="utf-8")
    monkeypatch.setattr(columns, "apply_classes", lambda *_: "bad")
    step = Step("columns", Who.AGENT, "Decide.", ask=Question("columns", "?", Kind.COLUMNS))
    script = Script(str(config), "y", "y", "", "", "n")
    with pytest.raises(Stopped):
        walk(Case("t", "", (_CONFIG, step)), script.terminal(), Calls())


def test_a_missing_file_is_said_without_its_path() -> None:
    def missing(_answers: object) -> None:
        path = "C:/secret/path/shop.yaml"
        raise FileNotFoundError(path)

    step = Step("copy", Who.AGENT, "Copy.", act=missing)
    script = Script("y")
    walk(Case("t", "", (step,)), script.terminal(), Calls())
    assert "FileNotFoundError" in script.text()
    assert "secret/path" not in script.text()


def test_every_step_says_what_it_is_once() -> None:
    step = Step("name", Who.AGENT, "The name of {thing}.", ask=Question("name", "Name?", Kind.TEXT))
    script = Script("shop")
    walk(Case("t", "", (step,)), script.terminal(), Calls())
    assert script.text().count("The name of <thing>.") == 1
