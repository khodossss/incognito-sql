"""Competitor configurations written from the marking: only columns a work does not show."""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from external_world import QUESTIONS, RECORDS, build

from bench.external import masks
from bench.external.work import Work, works


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Work, Work]:
    path, marking = build(tmp_path)
    base, closed = works(path, marking, QUESTIONS, RECORDS)  # the condition closes orders.total
    return base, closed


def test_protected_columns_are_those_not_shown(pair: tuple[Work, Work]) -> None:
    base, closed = pair
    assert masks.protected(base) == {
        "people": {"full_name": "identifier", "email": "identifier"},
        "orders": {"note": "free_text"},
    }
    assert masks.protected(closed)["orders"] == {"total": "identifier", "note": "free_text"}


def test_freepeak_masks_protected_names_whatever_their_case(pair: tuple[Work, Work]) -> None:
    connection = json.loads(masks.freepeak(pair[0]))["connections"][0]
    assert connection["database_path"] == "/data/shop.sqlite"
    (rule,) = connection["masking_rules"]
    assert rule["strategy"] == "fixed_string"
    assert re.fullmatch(rule["pattern"], "FULL_NAME")
    assert not re.fullmatch(rule["pattern"], "city")


def _with(work: Work, table: str, column: str, cls: str) -> Work:
    columns = {**work.marking.columns, table: {**work.marking.columns[table], column: cls}}
    schema = {**work.schema, table: {"name": "TEXT", **work.schema[table]}}
    return replace(work, schema=schema, marking=replace(work.marking, columns=columns))


def test_freepeak_nulls_secrets(pair: tuple[Work, Work]) -> None:
    work = _with(pair[0], "orders", "note", "secret")
    rules = json.loads(masks.freepeak(work))["connections"][0]["masking_rules"]
    assert {r["strategy"] for r in rules} == {"fixed_string", "null"}


def test_gate_and_januscope_list_every_spelling(pair: tuple[Work, Work]) -> None:
    denied = yaml.safe_load(masks.gate(pair[0]))["pii"]["column_denylist"]
    assert {"full_name", "FULL_NAME", "note", "NOTE"} <= set(denied)
    assert "city" not in denied
    rules = yaml.safe_load(masks.januscope(pair[0]))["redact"]["rules"]
    assert {"field": "**.email"} in rules
    assert {"field": "**.EMAIL"} in rules


def test_januscope_matches_name_at_the_root_only(pair: tuple[Work, Work]) -> None:
    work = _with(pair[0], "people", "name", "identifier")
    rules = yaml.safe_load(masks.januscope(work))["redact"]["rules"]
    assert {"field": "name"} in rules
    assert {"field": "**.name"} not in rules


def test_veil_declares_each_protected_column_with_its_kind(pair: tuple[Work, Work]) -> None:
    schema = masks.veil(pair[1])
    assert "model people {\n  /// @pii name\n  full_name String\n" in schema
    assert "  /// @pii email\n  email String" in schema
    assert "  /// @pii\n  note String" in schema
    assert "  /// @pii\n  total Float" in schema  # an identifier with no kind in its name
    assert "city" not in schema
