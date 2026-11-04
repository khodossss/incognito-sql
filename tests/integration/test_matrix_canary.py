"""On every DBMS no answer, describe() or audit line carries a canary from the database."""

import json

import pytest

from incognito_sql.core.pipeline import Gateway

from .conftest import Field

pytestmark = pytest.mark.integration
CANARY = "zqcanary"
CARD_NO = "4111111111111111"
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
    "SELECT DISTINCT customer_name FROM orders LIMIT 1",
    "SELECT full_name FROM people UNION SELECT customer_name FROM orders",
    "SELECT * FROM cards",
    "SELECT holder, card_no FROM cards",
    'SELECT * FROM "Clients"',
    'SELECT "FullName", COUNT(*) FROM "Clients" GROUP BY "FullName"',
    "SELECT * FROM information_schema.tables",
    "SELECT id FROM people WHERE phone = 549999999",
]
LABELS = "web_enabled: false\n"
ENTITIES = """entities:
  - {table: people, pk: id}
  - {table: orders, pk: id}
  - {table: cards, pk: card_no}
  - {table: Clients, pk: ClientId}
"""


@pytest.mark.parametrize(
    ("extra", "expect"),
    [("", "/v/tk_"), (LABELS, '"name_1"'), (LABELS + ENTITIES, '"Clients": [')],
)
def test_canary_absent_from_answers_and_audit(field: Field, extra: str, expect: str) -> None:
    gw = field.open(extra)
    text = json.dumps([gw.query(field.sql(sql), "c1") for sql in QUERIES], ensure_ascii=False)
    assert text.count('"rows"') >= 12  # the sweep did return data
    assert expect.casefold() in text.casefold()  # and took the path this case is about
    audit = field.audit.read_text(encoding="utf-8").casefold()
    for secret in (CANARY, CARD_NO):
        assert secret not in text.casefold()
        assert secret not in audit


def test_describe_shows_the_visible_window(gateway: Gateway) -> None:
    view = gateway.describe()
    tables = view["tables"]
    assert isinstance(tables, dict)
    assert tables["people"] == {
        "columns": {
            "id": "open",
            "full_name": "identifier",
            "city": "quasi",
            "phone": "identifier",
        },
        "hidden_columns": 2,
        "person_key": "id",
    }
    assert tables["staff"] == {"columns": {}, "hidden_columns": 2}
    clients = {k: v for k, v in tables.items() if k.casefold() == "clients"}
    [shown] = clients.values()
    assert {c.casefold(): v for c, v in shown["columns"].items()} == {
        "clientid": "open",
        "fullname": "identifier",
        "town": "quasi",
    }
    text = json.dumps(view).casefold()
    assert CANARY not in text
    for hidden in ("secret_note", "bio", "login"):
        assert hidden not in text
