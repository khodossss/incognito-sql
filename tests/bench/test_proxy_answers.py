"""Answers of gate (through DBHub), JanuScope and dbveil, without running them."""

from pathlib import Path

from bench.adapters import dbhub, dbveil, januscope_answers
from bench.adapters.base import ANSWERED, REFUSED
from bench.adapters.calls import parsed
from bench.dbms import Database


def test_dbhub_answers_are_the_last_statements_rows() -> None:
    one = '{"success":true,"data":{"statements":[{"sql":"x","rows":[{"n":"12"}],"count":1}]}}'
    assert dbhub.parse(one, is_error=False) == (ANSWERED, [["12"]])
    two = '{"success":true,"data":{"statements":[{"rows":[{"a":1}]},{"rows":[{"b":2}]}]}}'
    assert dbhub.parse(two, is_error=False) == (ANSWERED, [[2]])
    failed = '{"success":false,"error":"permission denied","code":"EXECUTION_ERROR"}'
    assert dbhub.parse(failed, is_error=False) == (REFUSED, None)


def test_dbhub_dsn_is_seen_from_the_sidecar() -> None:
    pg = Database("postgres", "u", "localhost", 5555, None, "abc", 5432)
    reader = "bench_reader:Bench_Reader_1"
    assert dbhub.dsn(pg) == f"postgres://{reader}@localhost:5432/world?sslmode=disable"
    assert dbhub.dsn(pg, 15432).startswith(f"postgres://{reader}@localhost:15432/")
    tsql = Database("tsql", "u", "localhost", 5555, None, "abc", 1433)
    assert dbhub.dsn(tsql).startswith("sqlserver://")
    lite = Database("sqlite", "sqlite:///w/world.sqlite", path=Path("w/world.sqlite"))
    assert dbhub.dsn(lite) == "sqlite:///data/world.sqlite"


def test_dbveil_answers_and_refusals() -> None:
    ok = '{"status": "ok", "columns": ["id"], "rows": [[1], [2]], "redactions": 0}'
    assert dbveil.parse(ok, is_error=False) == (ANSWERED, [[1], [2]])
    blocked = '{"status": "blocked", "reason": "only SELECT / SHOW / EXPLAIN are allowed"}'
    assert dbveil.parse(blocked, is_error=False) == (REFUSED, None)
    assert dbveil.parse('{"status": "error", "error": "x"}', is_error=False)[0] == REFUSED


def test_januscope_reads_a_printed_python_list() -> None:
    text = (
        "[{'id': 1, 'total': Decimal('631.96'), 'born': datetime.date(2001, 2, 3),"
        " 'x': None, 'neg': -2, 'n': \"[REDACTED]\"}]"
    )
    status, rows = januscope_answers.parse(text, is_error=False)
    assert status == ANSWERED
    assert rows == [[1, "631.96", "datetime.date(2001, 2, 3)", None, "-2", "[REDACTED]"]]


def test_januscope_reads_json_with_a_timing_line_and_an_html_table() -> None:
    mysql = '[\n  {"x": null, "n": 12}\n]\nQuery execution time: 3.61 ms'
    assert januscope_answers.parse(mysql, is_error=False) == (ANSWERED, [[None, 12]])
    html = "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>None</td></tr></table>"
    assert januscope_answers.parse(html, is_error=False) == (ANSWERED, [["1", None]])
    empty = "<table><tr><th>a</th></tr></table>"
    assert januscope_answers.parse(empty, is_error=False) == (ANSWERED, [])


def test_januscope_errors_are_refusals_and_prose_has_no_rows() -> None:
    assert januscope_answers.parse("Error: column x", is_error=False) == (REFUSED, None)
    assert januscope_answers.parse("no such column: x", is_error=True) == (REFUSED, None)
    assert parsed(januscope_answers.parse, "No results", is_error=False) == (ANSWERED, None)
    assert parsed(januscope_answers.parse, "[x for x in y]", is_error=False) == (ANSWERED, None)
