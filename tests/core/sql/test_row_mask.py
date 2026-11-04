"""Row rules: the masked copy the server puts in, and views that read past it."""

import pytest
import sqlglot

from incognito_sql.core.config import ColumnClass
from incognito_sql.core.config.row_rules import RowRule
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.row_mask import mask_rows, unruled_readers

from .conftest import CATALOG, DECL

RULE = RowRule(table="people", hide=["city"], where="id = 1")
RULED = DECL.model_copy(update={"row_rules": [RULE]})


def test_the_masked_copy_keeps_the_alias_and_every_column() -> None:
    tree = sqlglot.parse_one("SELECT p.city FROM people AS p", read="postgres")
    sql = mask_rows(tree, RULED, CATALOG).sql(dialect="postgres")
    assert 'CASE WHEN NOT (id = 1) THEN "city" END AS "city"' in sql
    assert ") AS p" in sql
    assert '"full_name"' in sql  # every column of the table, so any reference still binds


def test_a_table_without_rules_is_read_as_is() -> None:
    tree = sqlglot.parse_one("SELECT o.id FROM orders AS o", read="postgres")
    assert mask_rows(tree, RULED, CATALOG).sql(dialect="postgres") == "SELECT o.id FROM orders AS o"


def test_an_open_view_without_a_rule_or_a_mark_is_named() -> None:
    columns = {**DECL.columns, "cities": {"city": ColumnClass.QUASI}}
    decl = RULED.model_copy(update={"columns": columns})
    catalog = Catalog(
        columns={**CATALOG.columns, "cities": {"city": "TEXT"}}, views=frozenset({"cities"})
    )
    assert (
        unruled_readers(decl.model_copy(update={"verified_relations": ["cities"]}), catalog) == []
    )
    assert unruled_readers(decl, catalog) == ["cities"]
    assert unruled_readers(decl.model_copy(update={"row_rules": []}), catalog) == []
    own = RowRule(table="cities", hide=["city"], where="city = 'Zqtown'")
    ruled = decl.model_copy(update={"row_rules": [RULE, own]})
    assert unruled_readers(ruled, catalog) == ["cities"]  # its rule masks it, not its tables


def test_a_partition_or_child_of_a_ruled_table_is_named() -> None:
    columns = {
        **DECL.columns,
        "people_old": {"id": ColumnClass.OPEN},
        "deep": {"id": ColumnClass.OPEN},
    }
    decl = RULED.model_copy(update={"columns": columns})
    catalog = Catalog(
        columns={**CATALOG.columns, "people_old": {"id": "INT"}, "deep": {"id": "INT"}},
        parents={"people_old": frozenset({"people"}), "deep": frozenset({"people_old"})},
    )
    assert unruled_readers(decl, catalog) == ["deep", "people_old"]
    marked = decl.model_copy(update={"verified_relations": ["deep", "people_old"]})
    assert unruled_readers(marked, catalog) == []


def test_a_parent_of_a_ruled_partition_is_named_at_any_depth() -> None:
    columns = {**DECL.columns, "everyone": {"id": ColumnClass.OPEN}}
    rule = RowRule(table="orders", hide=["note"], where="id = 1")
    decl = DECL.model_copy(update={"columns": columns, "row_rules": [rule]})
    catalog = Catalog(
        columns={**CATALOG.columns, "everyone": {"id": "INT"}},
        parents={"orders": frozenset({"people"}), "people": frozenset({"everyone"})},
    )
    assert unruled_readers(decl, catalog) == ["everyone", "people"]
    marked = decl.model_copy(update={"verified_relations": ["everyone", "people"]})
    assert unruled_readers(marked, catalog) == []


def test_a_family_must_carry_the_same_rules() -> None:
    columns = {**DECL.columns, "people_old": {"id": ColumnClass.OPEN, "city": ColumnClass.QUASI}}
    catalog = Catalog(
        columns={**CATALOG.columns, "people_old": {"id": "INT", "city": "TEXT"}},
        parents={"people_old": frozenset({"people"})},
    )
    same = RowRule(table="people_old", hide=["city"], where=" id = 1")
    other = RowRule(table="people_old", hide=["city"], where="id = 2")
    decl = DECL.model_copy(update={"columns": columns, "row_rules": [RULE, same]})
    assert unruled_readers(decl, catalog) == []
    decl = decl.model_copy(update={"row_rules": [RULE, other]})
    assert unruled_readers(decl, catalog) == ["people", "people_old"]  # neither is stricter
    marked = decl.model_copy(update={"verified_relations": ["people", "people_old"]})
    assert unruled_readers(marked, catalog) == []


def test_a_with_query_named_like_a_ruled_table_is_refused() -> None:
    tree = sqlglot.parse_one(
        "WITH people AS (SELECT 1 AS id) SELECT id FROM people", read="postgres"
    )
    with pytest.raises(Rejection) as exc:
        mask_rows(tree, RULED, CATALOG)
    assert exc.value.reason is Reason.NODE_NOT_ALLOWED


def test_a_dropped_row_leaves_the_key_a_plain_column() -> None:
    rule = RowRule(table="people", hide="*", where="city = 'x'")
    decl = DECL.model_copy(update={"row_rules": [rule]})
    tree = sqlglot.parse_one("SELECT p.id FROM people AS p", read="postgres")
    sql = mask_rows(tree, decl, CATALOG).sql(dialect="postgres")
    assert "CASE" not in sql  # an index on the key still serves
    assert "WHERE NOT (city = 'x')" in sql
