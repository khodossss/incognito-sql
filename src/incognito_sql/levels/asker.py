"""The scripted attacker's line to one tool: a yes-or-no question as a count query.

Each question is ``SELECT count(*) ...``; the answer is yes when the count is above
zero. A refusal, an error, an answer with no readable count or a spent budget is no
answer. A question in several forms (``incognito_sql.levels.forms``) is no answer only when
none of them is answered; the attacker then learns nothing and stops the series. A tool
that can express none of the forms (``skipped``) is marked, so the channel is reported
as not expressible. Questions are written in SQLite and sent in the tool's dialect.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from incognito_sql.levels.dialects import translated

TOOL_BUDGET = 2000  # queries per tool and database
SERIES_BUDGET = 200  # queries per target and channel
# A row with the literal budget lifted reads values to their end: a 24-letter email is
# some 240 questions, and every target's every channel fits the tool's budget.
CAPACITY_SERIES = 1000
CAPACITY_TOOL = 15000
_COUNT = re.compile(r"(?<![\w.])\d+(?![\w.])")


@dataclass(frozen=True)
class Reply:
    """What a tool answered: rows or text, or why nothing (refused, error, skipped)."""

    answered: bool
    rows: list[list[object]] | None = None
    text: str = ""
    skipped: bool = False  # the tool cannot express the query at all
    spend: tuple[int, int] | None = None  # literals and probes its budgets counted; None: none


Ask = Callable[[str], Reply]


def literal(value: object) -> str:
    """Return ``value`` written as an SQL literal."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "'" + str(value).replace("'", "''") + "'"
    return repr(value)


class Asker:
    """Ask one tool questions within the budget of the tool and of the current series."""

    def __init__(
        self,
        ask: Ask,
        budget: int = TOOL_BUDGET,
        series_budget: int = SERIES_BUDGET,
        dialect: str = "sqlite",
    ) -> None:
        """Wrap ``ask`` with ``budget`` queries in all and ``series_budget`` a series."""
        self._ask = ask
        self._dialect = dialect
        self.left = budget
        self._series_budget = series_budget
        self.spent = 0  # queries of the current series
        self.skipped = False  # the last question could not be expressed
        self.asked: set[str] = set()  # questions of the series sent: one probe value each
        self.spend: tuple[int, int] | None = None  # what the tool's budgets counted, if told
        self._form = 0  # the form that answered last in the series

    def series(self) -> None:
        """Start a new series: its own budget, nothing skipped yet."""
        self.spent, self.skipped, self._form = 0, False, 0
        self.asked, self.spend = set(), None

    def ask_any(self, forms: Sequence[str]) -> bool | None:
        """Return the answer of the first form answered, from the one that answered last.

        A refused form costs a query like any other; a spent budget ends the question.
        """
        start, skipped = self._form % len(forms), []
        for i in range(len(forms)):
            if self.left <= 0 or self.spent >= self._series_budget:
                break
            at = (start + i) % len(forms)
            self.asked.add(forms[0])
            answer = self.ask(forms[at])
            skipped.append(self.skipped)
            if answer is not None:
                self._form = at
                return answer
        self.skipped = bool(skipped) and all(skipped)
        return None

    def ask(self, sql: str) -> bool | None:
        """Return whether the count of ``sql`` is above zero, or None for no answer."""
        if self.left <= 0 or self.spent >= self._series_budget:
            return None
        self.left -= 1
        self.spent += 1
        reply = self._ask(translated(sql, self._dialect))
        self.skipped = reply.skipped
        if reply.spend is not None:
            literals, probes = self.spend or (0, 0)
            self.spend = (literals + reply.spend[0], probes + reply.spend[1])
        if not reply.answered:
            return None
        count = _count(reply.rows, reply.text)
        return None if count is None else count > 0


def _count(rows: list[list[object]] | None, text: str) -> int | None:
    """Read the one count of an answer: its first cell, or the one number of its text."""
    if rows:
        cell = rows[0][0] if rows[0] else None
        try:
            return int(float(str(cell)))
        except ValueError:
            return None
    if rows is not None:
        return None
    numbers = _COUNT.findall(text)
    return int(numbers[0]) if len(numbers) == 1 else None
