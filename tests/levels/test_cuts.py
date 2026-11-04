"""The L2 cuts of a hidden column: what they return, and that they travel across dialects."""

import re
import sqlite3
from contextlib import closing

import pytest

from incognito_sql.levels.cuts import cuts
from incognito_sql.levels.fragment import needed

VALUE = "Avel Quorin-Westbrook"  # invented, 21 characters: a piece needs 11


def test_cuts_return_the_head_the_tail_a_split_and_the_extremes() -> None:
    with closing(sqlite3.connect(":memory:")) as con:
        con.execute('CREATE TABLE "people" ("full_name" TEXT)')
        con.executemany("INSERT INTO people VALUES (?)", [(VALUE,), ("Brisa",), (None,)])
        cases = cuts("people", "full_name", "sqlite")
        got = {case: con.execute(sql).fetchall() for case, sql in cases}
    need = needed(len(VALUE))
    assert got["people.full_name:head"] == [(VALUE[:need],), ("Brisa",)]
    assert got["people.full_name:tail"] == [(VALUE[-need:],), ("Brisa",)]
    assert got["people.full_name:split"][0] == (f"{VALUE[:11]} | {VALUE[11:]}",)
    assert got["people.full_name:minmax"] == [("Avel Quorin-Westbrook", "Brisa")]


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "tsql", "duckdb", "sqlite"])
def test_cuts_avoid_what_a_dialect_reads_otherwise(dialect: str) -> None:
    text = " ".join(sql for _, sql in cuts("people", "full_name", dialect)).upper()
    assert "GREATEST" not in text
    assert not re.search(r"(\(|,|FROM)\s*-", text)  # no negative start of a substring
    if dialect == "mysql":
        assert " DIV " in text  # `/` would be a decimal there
    if dialect == "postgres":
        assert "CAST(DIV(" in text  # DIV is numeric there; SUBSTRING wants an integer


def test_a_cut_in_sql_server_measures_a_value_with_its_trailing_spaces() -> None:
    text = " ".join(sql for _, sql in cuts("people", "full_name", "tsql"))
    assert "LEN(CONCAT([full_name], 'x')) - 1" in text
    assert "LEN([full_name])" not in text
