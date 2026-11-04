"""Row rules in the declaration: what a condition may read, what hide may name."""

from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from incognito_sql.core.config import load_declaration

Writer = Callable[..., Path]
RULE = {"table": "people", "hide": ["city"], "where": "id = 1"}
COLUMNS = {
    "people": {"id": "open", "full_name": "identifier", "city": "quasi", "notes": "free_text"},
    "orders": {"id": "open"},
}


def _rule(**override: object) -> list[dict[str, object]]:
    return [{**RULE, **override}]


def test_a_rule_on_open_columns_loads(write_yaml: Writer) -> None:
    decl = load_declaration(write_yaml(columns=COLUMNS, row_rules=_rule()))
    assert decl.row_rules[0].hide == ["city"]
    whole = load_declaration(
        write_yaml(columns=COLUMNS, row_rules=_rule(hide="*", where="city = 'Haifa'"))
    )
    assert whole.row_rules[0].hide == "*"


@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"table": "nowhere"}, "the table is not declared"),
        ({"hide": ["nosuch"]}, "hide names no column the model sees"),
        ({"hide": []}, "hide names no column the model sees"),
        ({"hide": ["notes"]}, "hide names no column the model sees"),
        ({"where": "full_name = 'Zqno'"}, "reads a column that is not open"),
        ({"where": "notes = 'x'"}, "reads a column that is not open"),
        ({"where": "id IN (SELECT id FROM people)"}, "not a plain comparison"),
        ({"where": "lower(city) = 'x'"}, "not a plain comparison"),
        ({"where": "orders.id = 1"}, "reads another table"),
        ({"where": "id = ("}, "does not parse"),
        ({"where": "id"}, "not a plain comparison"),
    ],
)
def test_a_bad_rule_stops_the_load(
    write_yaml: Writer, override: dict[str, object], problem: str
) -> None:
    with pytest.raises(ValidationError) as exc:
        load_declaration(write_yaml(columns=COLUMNS, row_rules=_rule(**override)))
    assert problem in str(exc.value)


def test_a_condition_may_not_read_a_cell_another_rule_hides(write_yaml: Writer) -> None:
    rules = [
        {"table": "people", "hide": ["city"], "where": "id = 1"},
        {"table": "people", "hide": ["id"], "where": "city = 'Haifa'"},
    ]
    with pytest.raises(ValidationError) as exc:
        load_declaration(write_yaml(columns=COLUMNS, row_rules=rules))
    assert "reads a column a row rule hides" in str(exc.value)
