"""The parser is the boundary: a new sqlglot is a reviewed event, never a silent upgrade."""

from importlib.metadata import version

TESTED_SQLGLOT = "30.25.0"  # the corpus and the five-DBMS matrix ran on this version


def test_sqlglot_is_the_tested_version() -> None:
    assert version("sqlglot") == TESTED_SQLGLOT
