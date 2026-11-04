"""`incognito-sql skill`: the agent's skill, written as `connect --write` writes."""

import argparse
from pathlib import Path

import pytest

from incognito_sql.cli import main
from incognito_sql.setup.guide import RULE
from incognito_sql.setup.skill import Place, run_skill, text

VERSION = "0.0.5a2"


def _never(_: str) -> str:
    raise AssertionError


def _place(home: Path, env: dict[str, str] | None = None, *, answer: str | None = None) -> Place:
    ask = _never if answer is None else (lambda _: answer)
    return Place(home, env or {}, answer is not None, ask, VERSION)


def _args(client: str, *, yes: bool = False) -> argparse.Namespace:
    return argparse.Namespace(client=client, yes=yes)


def test_the_skill_pins_this_version_and_keeps_the_guide_s_rule() -> None:
    skill = text(VERSION)
    assert skill.startswith("---\nname: incognito-sql\ndescription: ")
    assert f'uvx "incognito-sql=={VERSION}" guide' in skill
    assert RULE.strip() in skill  # never a password, DSN, key, token or value in the chat
    assert "uvx" not in text(None)  # a checkout runs the installation on the PATH


@pytest.mark.parametrize(
    ("client", "where"),
    [
        ("claude-code", (".claude", "skills")),
        ("codex", (".codex", "skills")),
        ("opencode", (".config", "opencode", "skill")),
    ],
)
def test_each_client_gets_it_in_its_skills_folder(
    client: str, where: tuple[str, ...], tmp_path: Path
) -> None:
    assert run_skill(_args(client, yes=True), _place(tmp_path)) == 0
    assert tmp_path.joinpath(*where, "incognito-sql", "SKILL.md").read_text(
        encoding="utf-8"
    ) == text(VERSION)


def test_a_folder_moved_by_a_variable_is_named_by_it_not_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    moved = tmp_path / "secret-looking-path"
    assert run_skill(_args("codex", yes=True), _place(tmp_path, {"CODEX_HOME": str(moved)})) == 0
    assert (moved / "skills" / "incognito-sql" / "SKILL.md").exists()
    err = capsys.readouterr().err
    assert "the codex skills folder (from CODEX_HOME)" in err
    assert str(moved) not in err


def test_without_a_terminal_it_writes_only_with_yes(tmp_path: Path) -> None:
    assert run_skill(_args("claude-code"), _place(tmp_path)) == 1
    assert not (tmp_path / ".claude").exists()


def test_it_writes_only_after_a_yes(tmp_path: Path) -> None:
    assert run_skill(_args("opencode"), _place(tmp_path, answer="n")) == 1
    assert not (tmp_path / ".config").exists()
    assert run_skill(_args("opencode"), _place(tmp_path, answer="y")) == 0
    assert (tmp_path / ".config" / "opencode" / "skill" / "incognito-sql" / "SKILL.md").exists()


def test_another_skill_there_is_replaced_only_after_a_yes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skill = tmp_path / ".codex" / "skills" / "incognito-sql" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("the user's own text", encoding="utf-8")
    asked: list[str] = []

    def no(question: str) -> str:
        asked.append(question)
        return ""

    place = Place(tmp_path, {}, True, no, VERSION)  # noqa: FBT003 -- a terminal
    assert run_skill(_args("codex"), place) == 1
    assert "Replace" in asked[0]
    assert skill.read_text(encoding="utf-8") == "the user's own text"
    assert run_skill(_args("codex", yes=True), _place(tmp_path)) == 0
    assert "replaced" in capsys.readouterr().err
    assert run_skill(_args("codex"), _place(tmp_path)) == 0  # the same text: nothing asked


def test_the_command_line_takes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert main(["skill", "codex", "--yes"]) == 0
    assert (tmp_path / "skills" / "incognito-sql" / "SKILL.md").exists()
    assert "(from CODEX_HOME)" in capsys.readouterr().err
