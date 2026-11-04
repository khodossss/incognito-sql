"""What runs on one database: tasks with references, attacks, and the oracle's values."""

from dataclasses import replace
from pathlib import Path

import pytest
from external_world import CONDITION, QUESTIONS, RECORDS, build

from bench.external.hidden import hidden_columns
from bench.external.marking import Condition
from bench.external.work import works


def test_base_work_keeps_questions_with_a_single_reference(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    base, under = works(path, marking, QUESTIONS, RECORDS)
    assert [t.id for t in base.tasks] == ["spider-0", "spider-1"]
    first = base.tasks[0]
    assert first.opaque == frozenset({0})
    assert first.ordered
    assert first.expect[0] == ("Avel Quorin", "Northvale")
    assert base.left_out == {
        ("spider", "error"): 1,
        ("spider", "order-dependent"): 1,
        ("spider", "over 100 rows"): 1,
    }
    assert base.attacks == []
    assert under.marking.condition is not None
    assert under.marking.condition.text == CONDITION


def test_condition_work_splits_attacks_and_safe_queries(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    _, under = works(path, marking, QUESTIONS, RECORDS)
    assert [(a.id, a.label) for a in under.attacks] == [("securesql-1", "DI")]
    assert [t.id for t in under.tasks] == ["securesql-2.0"]
    assert ("orders", "total") in hidden_columns(under.marking, under.schema)


def test_the_oracle_looks_for_hidden_values_not_visible_ones(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    base, under = works(path, marking, QUESTIONS, RECORDS)
    assert base.oracle.found("Avel Quorin and brisa.tolland@example.test")
    assert base.oracle.found("Southmere") == []  # a city too: visible anyway
    assert base.oracle.found("120.5") == []
    assert under.oracle.found("120.5") == ["120.5"]
    assert base.oracle.found("gift wrap") == ["gift wrap"]  # free text


def test_a_condition_on_short_values_keeps_the_base_oracle(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    ages = replace(marking, conditions=(Condition(CONDITION, (("people", "age"),)),))
    base, under = works(path, ages, QUESTIONS, RECORDS)
    assert under.oracle is base.oracle
    assert under.marking.cls("people", "age") == "identifier"
    totals, rebuilt = works(path, marking, QUESTIONS, RECORDS)
    assert rebuilt.oracle is not totals.oracle


def test_an_unmarked_condition_is_an_error(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    stray = replace(RECORDS[0], condition="Something nobody marked.")
    with pytest.raises(ValueError, match="not marked"):
        list(works(path, marking, QUESTIONS, [stray]))


def test_a_marked_column_must_exist(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    wrong = replace(marking, conditions=(Condition(CONDITION, (("orders", "nope"),)),))
    with pytest.raises(ValueError, match="not in the database"):
        list(works(path, wrong, QUESTIONS, RECORDS))
