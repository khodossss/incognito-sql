"""Labels mode: each label maps to the keys of the entity rows holding the value."""

import json
import random
from collections.abc import MutableSequence

import pytest

from .conftest import ALL_ENTITIES, CARD_NO, GatewayFactory

SQL = "SELECT customer_name, amount FROM orders WHERE person_id = 3"


class _Sorted(random.Random):
    """A shuffle that puts rows in a fixed order, to choose which spelling comes first."""

    def __init__(self, *, reverse: bool) -> None:
        super().__init__()
        self.reverse = reverse

    def shuffle(self, x: MutableSequence[object]) -> None:
        x[:] = sorted(x, key=str, reverse=self.reverse)


@pytest.mark.parametrize("reverse", [False, True])
def test_labels_find_keys_whichever_spelling_comes_first(
    make_gateway: GatewayFactory, monkeypatch: pytest.MonkeyPatch, *, reverse: bool
) -> None:
    gw = make_gateway("web_enabled: false\n")
    monkeypatch.setattr(gw, "_rng", _Sorted(reverse=reverse))
    out = gw.query(SQL, "c1")
    rows = out["rows"]
    assert isinstance(rows, list)
    assert {row[0] for row in rows} == {"name_1"}
    assert out["labels"] == {"name_1": {"people": [3]}}


def test_label_without_entity_keys(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("web_enabled: false\nentities: [{table: people, pk: full_name}]\n")
    out = gw.query(SQL, "c1")
    assert out["labels"] == {"name_1": {}}  # an identifier key is never shown


def test_keys_of_entities_stay_apart_and_personal_keys_drop(
    make_gateway: GatewayFactory,
) -> None:
    gw = make_gateway("web_enabled: false\n" + ALL_ENTITIES)
    gw.query("SELECT customer_name FROM orders", "c1")  # the store learns both spellings
    out = gw.query("SELECT holder FROM cards", "c1")
    labels = out["labels"]
    assert isinstance(labels, dict)
    [keys] = labels.values()
    assert isinstance(keys, dict)
    assert {t: sorted(map(str, k)) for t, k in keys.items()} == {
        "people": ["3"],
        "orders": ["11", "12"],
        "cards": ["c-7"],
    }
    assert CARD_NO not in json.dumps(out)
