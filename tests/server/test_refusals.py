"""Each refusal reason has a `retry` and a constant hint; the README lists them as the code does."""

import re
from pathlib import Path

import pytest

from incognito_sql.core.errors import Reason
from incognito_sql.mcp.refusals import GUIDE, Retry, explained

README = Path(__file__).parents[2] / "README.md"


def test_every_reason_has_a_retry_and_a_hint() -> None:
    assert {r.value for r in Reason} <= set(GUIDE)  # an entry may precede its reason
    for reason, (retry, hint) in GUIDE.items():
        assert isinstance(retry, Retry), reason
        assert hint.endswith("."), reason
        assert "tk_" not in hint, reason


@pytest.mark.parametrize(
    ("reason", "retry"),
    [
        (Reason.MULTIPLE_STATEMENTS, "rewrite"),
        (Reason.HIDDEN_COLUMN, "rewrite"),
        (Reason.LITERAL_BUDGET, "ask_user"),
        (Reason.INTERNAL_ERROR, "stop"),
    ],
)
def test_a_refusal_is_explained(reason: Reason, retry: str) -> None:
    refusal: dict[str, object] = {"error": reason.value, "sqlstate": "42000", "detail": "x"}
    answer = explained(refusal)
    assert answer == {**refusal, "retry": retry, "hint": GUIDE[reason.value][1]}  # nothing else


def test_answers_and_unknown_errors_stay_as_they_are() -> None:
    rows: dict[str, object] = {"columns": ["n"], "rows": [[1]]}
    assert explained(rows) is rows
    odd: dict[str, object] = {"error": "not_a_reason"}
    assert explained(odd) is odd


def test_the_readme_lists_every_reason_as_the_code_does() -> None:
    section = README.read_text("utf-8").split("### Refusal codes", 1)[1]
    text = section.split("\n## ", 1)[0]
    rows = re.findall(r"^\| `([a-z_]+)` \| `([a-z_]+)` \| (.+) \|$", text, re.MULTILINE)
    assert {r: (t, h) for r, t, h in rows} == {
        reason: (retry.value, hint) for reason, (retry, hint) in GUIDE.items()
    }
