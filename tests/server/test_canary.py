"""No response, describe() or audit line carries a canary from the database."""

import json

import pytest

from incognito_sql.core.pipeline import Gateway

from .conftest import ALL_ENTITIES, CANARY, CARD_NO, GatewayFactory, World

QUERIES = [
    "SELECT * FROM people",
    "SELECT full_name, city FROM people",
    "SELECT p.*, o.* FROM people p JOIN orders o ON o.person_id = p.id",
    "SELECT customer_name, COUNT(*) FROM orders GROUP BY customer_name",
    "SELECT COUNT(DISTINCT customer_name) FROM orders",
    "SELECT id FROM people WHERE full_name = 'Zqcanary Person'",
    "SELECT o.amount FROM orders o JOIN people p ON p.full_name = o.customer_name",
    "SELECT * FROM staff",
    "SELECT secret_note FROM people",
    "SELECT bio FROM people WHERE bio LIKE 'Zq%'",
    "SELECT full_name FROM people WHERE full_name LIKE 'Zq%'",
    "SELECT substr(full_name, 1, 2) FROM people",
    "SELECT full_name FROM people ORDER BY full_name",
    "SELECT login FROM staff",
    "SELECT * FROM sqlite_master",
    "SELECT id FROM people WHERE full_name IN ('Ivan Petrov', 'Anna Ivanova')",
    "SELECT * FROM cards",
    "SELECT holder, card_no FROM cards",
]
LABELS = "web_enabled: false\n"


def _sweep(gw: Gateway) -> str:
    return json.dumps([gw.query(sql, "c1") for sql in QUERIES], ensure_ascii=False)


@pytest.mark.parametrize(
    ("extra", "expect"),
    [
        ("", "/v/tk_"),
        (LABELS, '"name_1"'),
        (LABELS + ALL_ENTITIES, '"orders": ['),
        ("limits: {literal_budget: 1}\n", '"literal_budget"'),
    ],
)
def test_canary_absent_from_responses_and_audit(
    make_gateway: GatewayFactory, world: World, extra: str, expect: str
) -> None:
    gw = make_gateway(extra)
    text = _sweep(gw)
    assert '"rows"' in text  # the sweep did return data
    assert expect in text  # and took the path this case is about
    audit = world.audit.read_text(encoding="utf-8").casefold()
    for secret in (CANARY, CARD_NO):
        assert secret not in text.casefold()
        assert secret not in audit


def test_describe_shows_the_visible_window(gateway: Gateway) -> None:
    view = gateway.describe()
    assert view == {
        "dbms": "SQLite",
        "identifier_operations": [
            "contains",
            "count_distinct",
            "eq_literal",
            "eq_token",
            "group",
            "is_null",
            "join_ident",
            "length",
            "ne",
            "order",
            "output",
            "prefix",
        ],
        "tables": {
            "cards": {"columns": {"card_no": "open", "holder": "identifier"}, "hidden_columns": 0},
            "orders": {
                "columns": {
                    "id": "open",
                    "person_id": "open",
                    "customer_name": "identifier",
                    "amount": "open",
                },
                "hidden_columns": 0,
            },
            "people": {
                "columns": {"id": "open", "full_name": "identifier", "city": "quasi"},
                "hidden_columns": 2,
                "person_key": "id",
            },
            "staff": {"columns": {}, "hidden_columns": 2},
        },
    }
    text = json.dumps(view).casefold()
    assert CANARY not in text
    for hidden in ("secret_note", "bio", "login"):
        assert hidden not in text
