import json
import random
from datetime import datetime

from incognito_sql.core.config import Declaration
from incognito_sql.core.output.shape import shape
from incognito_sql.core.tokens.store import TokenStore

from .conftest import ID, OPEN, QUASI, labels_off, out_rows, rows

NAMES = [f"Zzperson {chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(50)]


def test_identifier_becomes_link_and_null_stays_null(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    data = [("Ivan Petrov", "Haifa"), (None, "Akko")]
    out = shape(rows(data), [ID, QUASI], store, decl, now, rng)
    col = [r[0] for r in out_rows(out)]
    assert None in col
    assert any(isinstance(c, str) and c.startswith("http://127.0.0.1:8765/v/tk_") for c in col)
    assert "Ivan" not in json.dumps(out)
    assert out["hidden_columns"] == 0
    assert out["truncated"] is False
    assert "labels" not in out


def test_web_off_labels(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    out = shape(
        rows([("Ivan Petrov", "Haifa")]),
        [ID, QUASI],
        store,
        labels_off(decl),
        now,
        rng,
        display_ids=lambda _v: {"people": [101, 102]},
    )
    assert out_rows(out)[0][0] == "name_1"
    assert out["labels"] == {"name_1": {"people": [101, 102]}}
    assert "Ivan" not in json.dumps(out)


def test_label_keys_that_look_personal_are_dropped(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    found: dict[str, list[object]] = {
        "cards": ["4111111111111111", "c-7"],
        "people": [3],
        "phones": ["+972 50 123 4567"],
    }
    out = shape(
        rows([("Ivan Petrov",)]),
        [ID],
        store,
        labels_off(decl),
        now,
        rng,
        display_ids=lambda _v: found,
    )
    assert out["labels"] == {"name_1": {"cards": ["c-7"], "people": [3]}}


def test_labels_without_display_ids_are_empty_and_null_stays_none(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    out = shape(rows([("Ivan Petrov",), (None,)]), [ID], store, labels_off(decl), now, rng)
    assert None in [r[0] for r in out_rows(out)]
    assert out["labels"] == {"name_1": {}}


def test_order_does_not_follow_values(store: TokenStore, decl: Declaration, now: datetime) -> None:
    data = [(n, n) for n in NAMES]
    out = shape(rows(data), [OPEN, ID], store, decl, now, random.Random(3))  # noqa: S311
    shown = [r[0] for r in out_rows(out)]
    assert sorted(map(str, shown)) == NAMES
    assert shown != NAMES


def test_label_numbers_not_alphabetical(
    store: TokenStore, decl: Declaration, now: datetime
) -> None:
    data = [(n, n) for n in NAMES]
    out = shape(rows(data), [ID, OPEN], store, labels_off(decl), now, random.Random(3))  # noqa: S311
    shown = out_rows(out)
    assert [r[0] for r in shown] == [f"name_{k}" for k in range(1, 51)]
    originals = [r[1] for r in shown]
    assert originals != NAMES
    assert originals != sorted(map(str, originals))


def test_group_by_variants_same_link_two_rows(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    out = shape(rows([("Ivan Petrov", 2), ("ivan petrov ", 1)]), [ID, OPEN], store, decl, now, rng)
    shown = out_rows(out)
    assert len(shown) == 2
    assert shown[0][0] == shown[1][0]
    assert sorted(str(r[1]) for r in shown) == ["1", "2"]


def test_label_mode_variants_share_label(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    data = [("Ivan Petrov", 2), ("ivan petrov ", 1), ("Anna Levi", 5)]
    out = shape(rows(data), [ID, OPEN], store, labels_off(decl), now, rng)
    labels = out["labels"]
    assert isinstance(labels, dict)
    assert len(labels) == 2
    by_count = {r[1]: r[0] for r in out_rows(out)}
    assert by_count[2] == by_count[1] != by_count[5]
