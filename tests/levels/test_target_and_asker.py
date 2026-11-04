"""Targets judged by a truth the caller reads, and questions sent in the tool's dialect."""

from incognito_sql.levels.asker import Asker, Reply
from incognito_sql.levels.target import Target, absent

TARGET = Target("people", "id", 1, "full_name", "Avel Quorin")  # invented


class Held:
    """A column that holds the given values, sorted as Python sorts."""

    def __init__(self, *values: object) -> None:
        self.values = set(values)

    def below(self, target: Target, probe: object) -> bool:
        return str(target.value) < str(probe)

    def holds(self, target: Target, value: object) -> bool:  # noqa: ARG002 -- one column
        return value in self.values


def test_absent_skips_forged_values_the_column_holds() -> None:
    first = absent(Held(), TARGET, "e")
    assert first not in {None, TARGET.value}
    assert absent(Held(first), TARGET, "e") not in {None, first, TARGET.value}


def test_a_question_goes_out_in_the_tool_dialect() -> None:
    sent: list[str] = []

    def ask(sql: str) -> Reply:
        sent.append(sql)
        return Reply(answered=True, rows=[[1]])

    sql = "SELECT count(*) FROM t WHERE instr(lower(c), 'ab') = 1"
    assert Asker(ask, dialect="postgres").ask(sql) is True
    assert Asker(ask).ask(sql) is True
    assert "POSITION" in sent[0]
    assert sent[1] == sql
