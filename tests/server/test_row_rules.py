"""Row rules end to end: the hidden cells are NULL to every part of the query."""

import pytest

from .conftest import GatewayFactory

CITY_OF_ONE = "row_rules: [{table: people, hide: [city], where: 'id = 1'}]\n"
NO_EILAT = "row_rules: [{table: people, hide: '*', where: \"city = 'Eilat'\"}]\n"
NAME_OF_THREE = "row_rules: [{table: people, hide: [full_name], where: 'id = 3'}]\n"


def test_a_hidden_cell_is_null(make_gateway: GatewayFactory) -> None:
    gw = make_gateway(CITY_OF_ONE)
    answer = gw.query("SELECT id, city FROM people ORDER BY id", "c1")
    assert answer["rows"] == [[1, None], [2, "Haifa"], [3, "Eilat"]]


def test_a_hidden_cell_is_null_to_conditions_and_aggregates(make_gateway: GatewayFactory) -> None:
    gw = make_gateway(CITY_OF_ONE)
    counted = gw.query("SELECT count(*) FROM people WHERE city = 'Haifa'", "c1")
    assert counted["rows"] == [[1]]
    grouped = gw.query("SELECT city, count(*) FROM people GROUP BY city ORDER BY city", "c1")
    assert grouped["rows"] == [[None, 1], ["Eilat", 1], ["Haifa", 1]]


def test_a_hidden_row_is_gone_from_joins(make_gateway: GatewayFactory) -> None:
    gw = make_gateway(NO_EILAT)
    assert gw.query("SELECT id FROM people ORDER BY id", "c1")["rows"] == [[1], [2]]
    joined = gw.query(
        "SELECT o.id FROM orders o JOIN people p ON o.person_id = p.id ORDER BY o.id", "c1"
    )
    assert joined["rows"] == [[10]]


def test_a_hidden_identifier_matches_nothing(make_gateway: GatewayFactory) -> None:
    gw = make_gateway(NAME_OF_THREE)
    found = gw.query("SELECT id FROM people WHERE full_name = 'Zqcanary Person'", "c1")
    assert found["rows"] == []
    rows = gw.query("SELECT id, full_name FROM people ORDER BY id", "c1")["rows"]
    assert isinstance(rows, list)
    assert [row[1] is None for row in rows] == [False, False, True]


def test_describe_names_the_columns_not_the_condition(make_gateway: GatewayFactory) -> None:
    view = make_gateway(CITY_OF_ONE).describe()
    people = view["tables"]["people"]  # type: ignore[index]
    assert people["hidden_in_some_rows"] == ["city"]
    assert "id = 1" not in str(view)


@pytest.mark.parametrize(
    ("rules", "sql", "refused"),
    [
        (NO_EILAT, "SELECT id FROM people WHERE id + 1 > 2", True),
        (NO_EILAT, "SELECT o.id FROM orders o JOIN people p ON o.person_id = p.id + 0", True),
        (NO_EILAT, "SELECT id + 1 FROM people", True),
        (NO_EILAT, "SELECT id + 1, count(*) FROM people GROUP BY id + 1", True),
        (NO_EILAT, "SELECT id FROM people GROUP BY id HAVING 1 / (id - 3) > -1", True),
        (
            NO_EILAT,
            "SELECT count(*) FROM (SELECT 1 / (id - 3) AS x FROM people) s WHERE x > -1",
            True,
        ),
        (
            NO_EILAT,
            "WITH s AS (SELECT 1 / (id - 3) AS x FROM people) SELECT count(*) FROM s",
            True,
        ),
        (NO_EILAT, "SELECT sum(id), count(*) FROM people", False),
        (
            NO_EILAT,
            "SELECT count(*) FROM people WHERE CASE WHEN id = 3 THEN 1 / 0 ELSE 0 END = 0",
            True,
        ),
        (
            NO_EILAT,
            (
                "SELECT count(*) FROM orders o JOIN people p ON o.person_id = p.id"
                " WHERE 1 / (o.id - 11) > -1"
            ),
            True,
        ),
        (NO_EILAT, "SELECT count(*) FROM orders WHERE 1 / (id - 11) > -1", False),
        (NO_EILAT, "SELECT count(*) FROM people WHERE id > -1 AND city = 'Haifa'", False),
        (NO_EILAT, "SELECT count(*) FROM people WHERE id > 0 AND id < 2 + 1", False),
        (NO_EILAT, "SELECT 1 / 0 FROM people WHERE id = 3", True),
        (NO_EILAT, "SELECT count(*) FROM people WHERE CAST('x' AS INTEGER) = 0", True),
        (NO_EILAT, "SELECT id FROM people WHERE id > 1", False),
        (
            NO_EILAT,
            "SELECT (SELECT count(*) FROM people q WHERE q.id + 1 > o.id) FROM orders o",
            True,
        ),
        (CITY_OF_ONE, "SELECT id FROM people WHERE id + 1 > 2", False),
    ],
)
def test_a_condition_that_can_fail_reads_no_table_with_dropped_rows(
    make_gateway: GatewayFactory,
    rules: str,
    sql: str,
    refused: bool,  # noqa: FBT001
) -> None:
    answer = make_gateway(rules).query(sql, "c1")
    assert (answer.get("error") == "hidden_rows") is refused


def test_a_hidden_key_gives_no_key(make_gateway: GatewayFactory) -> None:
    rule = "row_rules: [{table: people, hide: [id], where: \"city = 'Eilat'\"}]\n"
    labels = make_gateway(LABELS + rule).query(
        "SELECT customer_name FROM orders WHERE id = 11", "c1"
    )["labels"]
    assert isinstance(labels, dict)
    assert all(None not in keys.get("people", []) for keys in labels.values())


LABELS = "web_enabled: false\n"
NO_THREE = "row_rules: [{table: people, hide: '*', where: 'id = 3'}]\n"


@pytest.mark.parametrize("rule", [NO_THREE, NAME_OF_THREE])
def test_a_label_gives_no_key_of_a_hidden_row_or_cell(
    make_gateway: GatewayFactory, rule: str
) -> None:
    gw = make_gateway(LABELS + rule)
    answer = gw.query("SELECT customer_name FROM orders WHERE id = 11", "c1")
    labels = answer["labels"]
    assert isinstance(labels, dict)
    assert all(3 not in keys.get("people", []) for keys in labels.values())
    shown = make_gateway(LABELS).query("SELECT customer_name FROM orders WHERE id = 11", "c1")[
        "labels"
    ]
    assert isinstance(shown, dict)
    assert any(3 in keys.get("people", []) for keys in shown.values())  # the control


@pytest.mark.parametrize("sql", ["WITH people AS (SELECT 1 AS id) SELECT id FROM people"])
def test_a_with_query_named_like_the_table_is_refused(
    make_gateway: GatewayFactory, sql: str
) -> None:
    assert "error" in make_gateway(CITY_OF_ONE).query(sql, "c1")
