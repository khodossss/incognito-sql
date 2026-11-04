"""Identifier against identifier only within a cast-safe group (R69); literals keep their kinds."""

import pytest

from incognito_sql.core.config import ColumnClass, Declaration, Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.bind_values import coerce_raws
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import enforce
from incognito_sql.core.sql.resolve import qualify_tree
from incognito_sql.core.sql.typefamily import cast_group, literal_kind

from .reflected import reflected_types


@pytest.fixture(scope="module")
def typed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Catalog, Declaration]:
    types = reflected_types(tmp_path_factory.mktemp("types"))
    decl = Declaration(
        dsn_env="X",
        dialect="duckdb",
        columns={"w": dict.fromkeys(types, ColumnClass.IDENTIFIER)},
        entities=[],
    )
    return Catalog(columns={"w": types}), decl


REFUSED = [
    ("huge", "big"),
    ("uhuge", "big"),
    ("ubig", "big"),
    ("unsig", "big"),
    ("money", "dec"),
    ("money", "big"),
    ("smallmoney", "int"),
    ("dec", "dec12"),
    ("dec", "num"),
    ("flt", "dbl"),
    ("big", "dbl"),
    ("day", "stamp"),
    ("big", "vc"),
    ("none", "none2"),
    ("stamp", "stamptz"),
    ("pg_ts", "pg_tz"),
    ("stamp", "none"),
    ("arr", "dec"),
    ("udec", "udec12"),
    ("udec", "dec2"),
]
ALLOWED = [
    ("big", "int"),
    ("small", "i8"),
    ("dec", "dec2"),
    ("money", "money2"),
    ("day", "day2"),
    ("vc", "nvc"),
    ("txt", "vc"),
    ("stamptz", "pg_tz"),
    ("stamp", "pg_ts"),
]


def _policy(sql: str, typed: tuple[Catalog, Declaration]) -> list[int] | Reason:
    catalog, decl = typed
    try:
        tree = qualify_tree(parse(sql, "duckdb", Limits()), catalog, "duckdb")
        return enforce(tree, catalog, decl).pii_outputs
    except Rejection as exc:
        return exc.reason


def _queries(a: str, b: str) -> list[str]:
    return [
        f"SELECT {a} FROM w WHERE {a} = {b}",  # noqa: S608 -- names of the test catalog
        f"SELECT {a} FROM w WHERE {b} IN ({a})",  # noqa: S608
        f"SELECT {a} FROM w UNION ALL SELECT {b} FROM w",  # noqa: S608
    ]


@pytest.mark.parametrize(("a", "b"), REFUSED)
def test_pairs_outside_one_group_are_refused(
    a: str, b: str, typed: tuple[Catalog, Declaration]
) -> None:
    for sql in _queries(a, b):
        assert _policy(sql, typed) is Reason.LITERAL_TYPE_MISMATCH, sql


@pytest.mark.parametrize(("a", "b"), ALLOWED)
def test_pairs_in_one_group_pass(a: str, b: str, typed: tuple[Catalog, Declaration]) -> None:
    for sql in _queries(a, b):
        assert _policy(sql, typed) == [0], sql


@pytest.mark.parametrize(
    ("column_type", "group"),
    [
        ("BIGINT", "integer"),
        ("INT8", "integer"),
        ("TINYINT", "integer"),
        ("HUGEINT", "HUGEINT"),
        ("BIGINT UNSIGNED", "BIGINT UNSIGNED"),
        ("INT(10) ZEROFILL", "INT UNSIGNED"),  # MySQL: ZEROFILL implies UNSIGNED
        ("DECIMAL(10, 2) UNSIGNED", "DECIMAL(10,2) UNSIGNED"),
        ("TIMESTAMP WITH TIME ZONE", "TIMESTAMP WITH TIME ZONE"),
        ("TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"),
        ("TIME WITH TIME ZONE", "TIME WITH TIME ZONE"),
        ("TIMESTAMP", "TIMESTAMP"),
        ("DECIMAL(10,2)[]", "DECIMAL(10,2)[]"),
        ("DECIMAL(10, 2) []", "DECIMAL(10,2)[]"),  # one spelling, one group
        ("STRUCT(a INTEGER)", "STRUCT(A INTEGER)"),
        ("NUMERIC(10, 2)", "NUMERIC(10,2)"),
        ("NUMERIC", "NUMERIC"),
        ("DOUBLE PRECISION", "DOUBLE"),
        ("CHARACTER VARYING(10)", "character"),
        ("STRING", "character"),
        ("", ""),
    ],
)
def test_cast_group(column_type: str, group: str) -> None:
    assert cast_group(column_type) == group


def test_literal_kinds_and_binds_keep_their_own_table(typed: tuple[Catalog, Declaration]) -> None:
    assert literal_kind("HUGEINT") == "number"
    assert literal_kind("MONEY") is None  # `m = 5` stays refused
    assert literal_kind("NVARCHAR(10)") == "text"
    assert coerce_raws(["12"], "HUGEINT") == [12]
    assert coerce_raws(["$12.50"], "MONEY") == ["$12.50"]  # a token's raw form, not parsed
    assert literal_kind("DECIMAL(10,2)[]") is None
    assert _policy("SELECT money FROM w WHERE money = 5", typed) is Reason.LITERAL_TYPE_MISMATCH
    assert _policy("SELECT arr FROM w WHERE arr = 5", typed) is Reason.LITERAL_TYPE_MISMATCH
