"""Hours a tool's budgets make an inference series wait, from what its budgets counted."""

import pytest

from incognito_sql.levels.asker import Asker, Reply
from incognito_sql.levels.infer import Budgets, wait

HOUR = 3600


@pytest.mark.parametrize(
    ("spends", "budgets", "hours"),
    [
        ([], Budgets(20, 100, HOUR), "-"),  # nothing inferred, or a tool that counts nothing
        ([(20, 100)], Budgets(20, 100, HOUR), "0"),  # the first window is free
        ([(41, 0)], Budgets(20, 100, HOUR), "2"),
        ([(0, 201)], Budgets(20, 100, HOUR), "2"),
        ([(41, 0)], Budgets(None, 100, HOUR), "unlimited"),
        ([(41, 250)], Budgets(None, None, HOUR), "unlimited"),
        ([(41, 250)], Budgets(None, 100, HOUR), "2"),  # the probes still wait
        ([(41, 0)], Budgets(0, 100, HOUR), "closed"),
        ([(0, 5)], Budgets(20, 0, HOUR), "closed"),
        ([(0, 5)], Budgets(0, 100, HOUR), "0"),  # literals off: this series needs none
        ([(41, 0)], Budgets(20, 100, 60), "0.0333333"),
    ],
)
def test_wait_reads_each_budget_as_given(
    spends: list[tuple[int, int]], budgets: Budgets, hours: str
) -> None:
    assert wait(spends, budgets) == hours


def test_a_series_adds_up_what_the_tool_says_it_spent() -> None:
    replies = iter(
        [
            Reply(answered=True, rows=[[1]], spend=(1, 2)),
            Reply(answered=False, spend=(0, 0)),  # refused: spent nothing
            Reply(answered=True, rows=[[0]], spend=(0, 1)),
        ]
    )
    asker = Asker(lambda _: next(replies))
    asker.series()
    for _ in range(3):
        asker.ask("SELECT count(*) FROM t")
    assert asker.spend == (1, 3)
    asker.series()
    assert asker.spend is None


def test_a_tool_that_tells_no_spend_has_none() -> None:
    asker = Asker(lambda _: Reply(answered=True, rows=[[1]]))
    asker.series()
    asker.ask("SELECT count(*) FROM t")
    assert asker.spend is None
