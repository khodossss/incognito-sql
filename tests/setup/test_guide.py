"""`incognito-sql guide`: the steps as text, the rule on secrets first."""

import pytest

from incognito_sql.cli import main
from incognito_sql.setup.cases import CASES
from incognito_sql.setup.guide import RULE


def _guide(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(["guide", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_the_whole_guide_starts_with_the_rule_and_lists_every_case(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = _guide(capsys)
    assert code == 0
    assert out.splitlines()[1] == RULE.strip()
    for case in CASES:
        assert f"\n== {case.name}: " in out


def test_a_human_s_step_says_it_is_not_the_agent_s(capsys: pytest.CaptureFixture[str]) -> None:
    _, out, _ = _guide(capsys, "--case", "own")
    block = out.split("[password]")[1].split("\n[")[0]
    assert "the human, in their own terminal or client (not you)" in block
    assert "run: incognito-sql secret" in block


def test_from_starts_at_the_step(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _guide(capsys, "--case", "own", "--from", "init")
    assert code == 0
    assert "[init]" in out
    assert "[password]" not in out


@pytest.mark.parametrize("argv", [("--from", "init"), ("--case", "own", "--from", "nosuch")])
def test_a_bad_from_is_refused(capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]) -> None:
    code, out, err = _guide(capsys, *argv)
    assert code == 2
    assert not out
    assert "--from" in err
