"""The plain-input prompter: numbers, names, ranges, defaults, and asking again."""

import pytest

from .conftest import Script

OPTIONS = ("claude-code", "codex", "cursor", "opencode")


@pytest.mark.parametrize(("typed", "picked"), [("2", "codex"), ("opencode", "opencode")])
def test_one_takes_a_number_or_a_name(typed: str, picked: str) -> None:
    assert Script(typed).terminal().one("Client?", OPTIONS, None) == picked


def test_one_takes_the_default_on_an_empty_line() -> None:
    assert Script("").terminal().one("Client?", OPTIONS, "cursor") == "cursor"


@pytest.mark.parametrize("wrong", ["9", "0", "x", "1,2", "1-2"])
def test_one_asks_again_until_one_option_is_named(wrong: str) -> None:
    script = Script(wrong, "1")
    assert script.terminal().one("Client?", OPTIONS, None) == "claude-code"
    assert "one number" in script.text()


def test_many_takes_numbers_ranges_and_names_once_each() -> None:
    picked = Script("4,1-2,codex").terminal().many("Which?", OPTIONS, [])
    assert picked == ["opencode", "claude-code", "codex"]


def test_many_keeps_the_chosen_on_an_empty_line() -> None:
    script = Script("")
    assert script.terminal().many("Which?", OPTIONS, ["cursor"]) == ["cursor"]
    assert "[3]" in script.text()


@pytest.mark.parametrize("wrong", ["3-1", "2-9", "a-b", ","])
def test_many_asks_again_on_a_wrong_range(wrong: str) -> None:
    script = Script(wrong, "1")
    assert script.terminal().many("Which?", OPTIONS, []) == ["claude-code"]
    assert "e.g. 1,3-5" in script.text()


@pytest.mark.parametrize(
    ("typed", "default", "answer"),
    [("y", False, True), ("NO", True, False), ("", True, True), ("", False, False)],
)
def test_yesno(typed: str, *, default: bool, answer: bool) -> None:
    assert Script(typed).terminal().yesno("Go on?", default=default) is answer


def test_yesno_asks_again_on_anything_else() -> None:
    script = Script("maybe", "y")
    assert script.terminal().yesno("Go on?", default=False) is True
    assert "answer y or n" in script.text()


def test_text_asks_again_until_valid() -> None:
    script = Script("shop_dsn", "", "SHOP_DSN")
    assert script.terminal().text("Variable?", None, str.isupper) == "SHOP_DSN"
    assert script.text().count("not accepted") == 2


def test_text_takes_the_default_on_an_empty_line() -> None:
    script = Script("")
    assert script.terminal().text("Folder?", ".", None) == "."
    assert "Folder? [.]: " in script.shown
