"""Stars expand to visible columns; hidden ones are counted; outputs are classified."""

import pytest

from incognito_sql.core.config import ColumnClass

from .conftest import DIALECTS, PrepareRun

ID = ColumnClass.IDENTIFIER
OPEN = ColumnClass.OPEN
QUASI = ColumnClass.QUASI
PEOPLE: list[ColumnClass | None] = [OPEN, ID, ID, QUASI]
ORDERS: list[ColumnClass | None] = [OPEN, ID, OPEN, OPEN]

# Each case: the query, its hidden count, its output classes.
OUTER: list[tuple[str, int, list[ColumnClass | None]]] = [
    ("SELECT * FROM people", 1, PEOPLE),
    (
        "SELECT p.*, o.id FROM people p JOIN orders o ON o.customer_name = p.full_name",
        1,
        [*PEOPLE, OPEN],
    ),
    ("SELECT * FROM people p CROSS JOIN orders o", 1, PEOPLE + ORDERS),
    ("SELECT o.*, p.* FROM people p JOIN orders o ON o.id = p.id", 1, ORDERS + PEOPLE),
    ("SELECT p.*, o.customer_name FROM people p JOIN orders o ON o.id = p.id", 1, [*PEOPLE, ID]),
    ("SELECT a.*, p.id FROM audit_shadow a JOIN people p ON p.id = p.id", 3, [OPEN]),
    ("SELECT p.*, q.* FROM people p JOIN people q ON q.id = p.id", 2, PEOPLE + PEOPLE),
    # a computed or merged output takes its most sensitive source
    ("SELECT coalesce(p.city, o.note) FROM people p JOIN orders o ON o.id = p.id", 0, [QUASI]),
    ("SELECT note FROM orders UNION SELECT city FROM people", 0, [QUASI]),
    ("SELECT count(*) FROM people", 0, [OPEN]),
    ("SELECT CAST(count(*) AS TEXT), 1.5 FROM people", 0, [OPEN, OPEN]),
    ("SELECT d.full_name FROM (SELECT * FROM people) d", 0, [ID]),
    ("WITH c AS (SELECT * FROM people) SELECT c.id FROM c", 0, [OPEN]),
]


def test_select_star_hides_unmarked_table(prepare_sql: PrepareRun) -> None:
    p = prepare_sql("SELECT * FROM audit_shadow")  # the table is not in the declaration
    assert p.hidden_count == 3
    assert p.output_classes == []
    assert p.sql == ""
    assert p.params == {}


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "hidden", "classes"), OUTER)
def test_outer_expansion(
    prepare_sql: PrepareRun,
    dialect: str,
    sql: str,
    hidden: int,
    classes: list[ColumnClass | None],
) -> None:
    p = prepare_sql(sql, dialect)
    assert (p.hidden_count, p.output_classes) == (hidden, classes)
    assert "notes" not in p.sql
    assert "audit_shadow.a" not in p.sql


@pytest.mark.parametrize("dialect", DIALECTS)
def test_star_expands_in_catalog_order(prepare_sql: PrepareRun, dialect: str) -> None:
    sql = prepare_sql("SELECT * FROM people", dialect).sql
    assert sql.startswith(
        "SELECT people.id, people.full_name, people.phone, people.city FROM people ORDER BY"
    )


@pytest.mark.parametrize("dialect", DIALECTS)
def test_star_after_a_column_expands_in_place(prepare_sql: PrepareRun, dialect: str) -> None:
    p = prepare_sql("SELECT o.id, p.* FROM people p JOIN orders o ON o.id = p.id", dialect)
    assert p.sql.startswith("SELECT o.id AS id, p.id, p.full_name, p.phone, p.city FROM")
    assert p.output_classes == [OPEN, *PEOPLE]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_nested_stars_expand(prepare_sql: PrepareRun, dialect: str) -> None:
    sql = prepare_sql(
        "SELECT id FROM people WHERE EXISTS (SELECT * FROM orders o WHERE o.id = people.id)",
        dialect,
    ).sql
    assert "EXISTS(SELECT o.id, o.customer_name, o.note, o.amount FROM orders AS o" in sql
    assert "*" not in sql


@pytest.mark.parametrize("dialect", DIALECTS)
def test_nested_star_over_hidden_table_selects_null(prepare_sql: PrepareRun, dialect: str) -> None:
    sql = prepare_sql(
        "SELECT id FROM people WHERE EXISTS (SELECT * FROM audit_shadow)", dialect
    ).sql
    assert "EXISTS(SELECT NULL FROM audit_shadow)" in sql


@pytest.mark.parametrize("dialect", DIALECTS)
def test_count_star_is_not_expanded(prepare_sql: PrepareRun, dialect: str) -> None:
    assert "COUNT(*)" in prepare_sql("SELECT count(*) FROM people", dialect).sql
