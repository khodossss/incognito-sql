"""A token compared with a typed identifier: rows or none, never a refusal or an error.

A token's raw forms are stored data; whether one of them fits the column's type
must not change the kind of answer. Enumerated types are refused by column type.
"""

import pytest

from incognito_sql.core.pipeline import Gateway

from .conftest import Field
from .test_matrix import rows, token
from .test_matrix_families import MISMATCH

pytestmark = pytest.mark.integration
NONE: list[list[object]] = []
ONE: list[list[object]] = [[1]]
TEXTS = [1, 2, 3, 4]  # 'not a date', 'maybe', '2020-13-45', '1e30'
# (source column, its row, target column, expected rows)
Probe = tuple[str, int, str, list[list[object]]]


def _texts(*targets: str) -> list[Probe]:
    return [("txt", pk, target, NONE) for pk in TEXTS for target in targets]


def _own(*columns: str) -> list[Probe]:
    """A column's own token finds its row."""
    return [(column, 1, column, ONE) for column in columns]


PROBES: dict[str, list[Probe]] = {
    "postgres": [
        ("d12", 1, "d10", NONE),
        ("d12", 2, "d10", ONE),
        ("num", 1, "mo", NONE),
        ("num", 2, "mo", ONE),
        ("txt", 5, "dt", ONE),
        *_texts("dt", "ts", "tz", "u", "bo", "mo"),
        *_own("tz", "u", "bo", "mo"),
    ],
    "sqlite": [
        ("txt", 1, "ib", NONE),
        ("txt", 1, "ubi", NONE),
        ("txt", 2, "ib", NONE),
        ("txt", 3, "ib", ONE),
    ],
    "mysql": [
        ("d40", 1, "ub", NONE),
        ("d40", 2, "ub", ONE),
        ("neg", 1, "ub", NONE),  # MySQL's CAST(-5 AS UNSIGNED) wraps to row 3's value
        ("neg", 2, "ub", ONE),
        ("d12", 1, "d10", NONE),
        ("d12", 2, "d10", ONE),
        *_own("dtf"),
    ],
    "duckdb": [
        ("hi", 1, "ub", NONE),
        ("hi", 2, "ub", ONE),
        ("neg", 1, "ub", NONE),
        ("neg", 1, "uh", NONE),
        ("d12", 1, "d10", NONE),
        ("d12", 2, "d10", ONE),
        ("dbl", 1, "f", NONE),
        ("dbl", 2, "f", ONE),
        ("txt", 5, "dt", ONE),
        *_texts("dt", "ts", "tz", "u", "bo"),
        *_own("tz", "u", "bo"),
    ],
    "tsql": [
        ("d12", 1, "d10", NONE),
        ("d12", 2, "d10", ONE),
        ("d38", 1, "d10", NONE),
        ("d38", 2, "d10", ONE),
        ("d38", 1, "mo", NONE),
        ("d38", 1, "sm", NONE),
        ("d38", 2, "mo", ONE),
        ("dt2", 1, "dtm", NONE),
        *_texts("dt2", "dtm", "dto", "u", "mo", "sm", "f"),
        *_own("dto", "u", "mo"),
    ],
}
# Refused by the column's type alone, for a literal and for a token alike.
BY_TYPE = {
    "postgres": [("e", "e")],
    "mysql": [("e", "e"), ("du", "d12"), ("dbu", "d12"), ("fu", "d12")],
    "duckdb": [("e", "e")],
}
LITERALS = {"e": "'calm'", "du": "5.5", "dbu": "5", "fu": "5"}


def _token(gateway: Gateway, column: str, pk: int) -> str:
    [[cell]] = rows(gateway.query(f"SELECT {column} FROM probes WHERE id = {pk}", "c1"))  # noqa: S608
    return token(cell)


def _answer(out: dict[str, object]) -> object:
    found = out.get("rows")
    return [list(row) for row in found] if isinstance(found, list) else out


def test_tokens_meet_typed_identifiers_without_refusal(field: Field, gateway: Gateway) -> None:
    probes = PROBES[field.backend.dialect]
    wrong = []
    for source, pk, target, expected in probes:
        tk = _token(gateway, source, pk)
        out = gateway.query(f"SELECT id FROM probes WHERE {target} = '{tk}'", "c1")  # noqa: S608
        if _answer(out) != expected:
            wrong.append((source, pk, target, _answer(out)))
    assert wrong == []


def test_enumerated_and_inexpressible_types_are_refused(field: Field, gateway: Gateway) -> None:
    cases = BY_TYPE.get(field.backend.dialect)
    if cases is None:
        pytest.skip("no such column in this world")
    for target, source in cases:
        tk = _token(gateway, source, 1)
        for value in (LITERALS[target], f"'{tk}'"):
            sql = f"SELECT id FROM probes WHERE {target} = {value}"  # noqa: S608
            assert gateway.query(sql, "c1") == MISMATCH, sql
