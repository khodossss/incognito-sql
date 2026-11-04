import json
import random
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from incognito_sql.core.config import Declaration
from incognito_sql.core.exec.run import Rows
from incognito_sql.core.output.mask import MASK
from incognito_sql.core.output.shape import shape
from incognito_sql.core.tokens.store import TokenStore

from .conftest import ID, OPEN, QUASI, out_rows, rows

CANARY = "Zqcanary Person"
TOKEN = re.compile(r"tk_[a-z2-7]{16}")


def test_open_cell_with_email_is_masked(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    out = shape(rows([("ivan@example.com", "ok")]), [OPEN, OPEN], store, decl, now, rng)
    assert out_rows(out)[0] == [MASK, "ok"]
    assert ord(MASK[0]) == 0x2039
    assert ord(MASK[-1]) == 0x203A
    assert "ivan@example.com" not in json.dumps(out)


def test_cell_types_are_json_safe(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    moment = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    data = [(Decimal("12.50"), date(2026, 1, 2), moment, b"\x01\x02", 7, 1.5, True)]
    out = shape(rows(data), [OPEN] * 7, store, decl, now, rng)
    assert out_rows(out)[0] == [
        "12.50",
        "2026-01-02",
        "2026-01-02T03:04:00+00:00",
        "\u2039bytes\u203a",
        7,
        1.5,
        True,
    ]
    json.dumps(out, allow_nan=False)


def test_nonfinite_float_is_text(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    out = shape(rows([(float("nan"),)]), [OPEN], store, decl, now, rng)
    json.dumps(out, allow_nan=False)


def test_hidden_truncated_columns_pass_through(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    out = shape(rows([(1,)], truncated=True), [OPEN], store, decl, now, rng, hidden_count=3)
    assert out["hidden_columns"] == 3
    assert out["truncated"] is True
    assert out["columns"] == ["c0"]


@pytest.mark.parametrize("web", [True, False])
def test_no_plaintext_anywhere(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random, *, web: bool
) -> None:
    d = decl.model_copy(update={"web_enabled": web})
    out = shape(
        rows([(CANARY, "Haifa"), (CANARY.upper(), "Akko")]),
        [ID, QUASI],
        store,
        d,
        now,
        rng,
        display_ids=lambda _v: {"people": [1]},
    )
    blob = TOKEN.sub("", json.dumps(out)).lower()  # a random token may hold "zq"
    assert "canary" not in blob
    assert "zq" not in blob


def test_empty_rows(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    out = shape(Rows(columns=[], rows=[], truncated=False), [], store, decl, now, rng)
    assert out["rows"] == []


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (float("nan"), "nan"),
        (float("inf"), "inf"),
        (UUID("6f1c3a52-8e0b-4b7e-9a4d-2f1c8d7e5a10"), "6f1c3a52-8e0b-4b7e-9a4d-2f1c8d7e5a10"),
        (timedelta(days=1, hours=2), "1 day, 2:00:00"),
    ],
)
def test_other_cells_are_shown_as_text(
    store: TokenStore, decl: Declaration, now: datetime, value: object, shown: str
) -> None:
    out = shape(rows([(value,)]), [OPEN], store, decl, now, random.Random(0))  # noqa: S311
    assert out_rows(out)[0] == [shown]


def test_row_wider_than_its_classes_is_refused(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 -- zip(strict=True) words it, not us
        shape(rows([("Haifa", CANARY)]), [OPEN], store, decl, now, rng)
