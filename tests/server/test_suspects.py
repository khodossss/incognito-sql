"""Open cells that look personal: a link for the human, a line for the admin."""

import json
import logging
import re

import pytest

from incognito_sql.core.output.mask import MASK

from .conftest import CARD_NO, GatewayFactory, World

CONN = "c1"
MASK_LINK = re.compile(r"http://127\.0\.0\.1:8765/m/(tk_[a-z2-7]{16})")
VERIFIED = "verified_open: {cards: [card_no]}\n"


def _audit(world: World) -> list[dict[str, object]]:
    return [json.loads(x) for x in world.audit.read_text(encoding="utf-8").splitlines()]


def _cells(out: dict[str, object]) -> list[object]:
    rows = out["rows"]
    assert isinstance(rows, list)
    return sorted((row[0] for row in rows), key=str)


def test_a_suspicious_cell_is_a_mask_link_and_the_admin_is_told(
    make_gateway: GatewayFactory, world: World, caplog: pytest.LogCaptureFixture
) -> None:
    gateway = make_gateway("")
    with caplog.at_level(logging.WARNING):
        out = gateway.query("SELECT card_no FROM cards", CONN)
        gateway.query("SELECT card_no FROM cards", CONN)
    plain, masked = _cells(out)
    assert plain == "c-7"
    assert MASK_LINK.fullmatch(str(masked))
    assert CARD_NO not in json.dumps(out)
    assert [line["masked"] for line in _audit(world)] == [["cards.card_no: card"]] * 2
    warned = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warned) == 1  # once per column, not per query
    assert "cards.card_no" in warned[0]
    assert "(card)" in warned[0]
    assert "verified_open" in warned[0]
    assert CARD_NO not in warned[0]


def test_a_mask_token_does_not_bind_in_sql(make_gateway: GatewayFactory) -> None:
    gateway = make_gateway("")
    masked = _cells(gateway.query("SELECT card_no FROM cards", CONN))[1]
    match = MASK_LINK.fullmatch(str(masked))
    assert match is not None
    sql = f"SELECT holder FROM cards WHERE holder = '{match.group(1)}'"  # noqa: S608
    out = gateway.query(sql, CONN)
    assert out["error"] == "invalid_token"


def test_labels_mode_keeps_the_text_mask(make_gateway: GatewayFactory) -> None:
    out = make_gateway("web_enabled: false\n").query("SELECT card_no FROM cards", CONN)
    assert _cells(out) == ["c-7", MASK]


@pytest.mark.parametrize("sql", ["SELECT card_no FROM cards", "SELECT * FROM cards"])
def test_a_verified_column_passes_straight(
    make_gateway: GatewayFactory, world: World, sql: str
) -> None:
    out = make_gateway(VERIFIED).query(sql, CONN)
    assert CARD_NO in json.dumps(out)
    assert _audit(world)[0]["masked"] == []


@pytest.mark.parametrize(
    ("sql", "tables"),
    [
        ("SELECT TRIM(card_no) AS c FROM cards", "cards"),
        ("SELECT x FROM (SELECT card_no AS x FROM cards) AS t", "cards"),
        ("WITH t AS (SELECT card_no FROM cards) SELECT card_no FROM t", "cards"),
        ("SELECT card_no FROM cards UNION ALL SELECT city FROM people", "cards, people"),
    ],
)
def test_verified_does_not_cover_what_is_not_the_column_itself(
    make_gateway: GatewayFactory, world: World, sql: str, tables: str
) -> None:
    out = make_gateway(VERIFIED).query(sql, CONN)
    assert "error" not in out
    assert CARD_NO not in json.dumps(out)
    assert _audit(world)[0]["masked"] == [f"a computed result column over {tables}: card"]


def test_computed_columns_warn_once_per_set_of_tables(
    make_gateway: GatewayFactory, caplog: pytest.LogCaptureFixture
) -> None:
    gateway = make_gateway("")
    with caplog.at_level(logging.WARNING):
        gateway.query("SELECT TRIM(card_no) AS c FROM cards", CONN)
        gateway.query("SELECT UPPER(card_no) AS c FROM cards", CONN)
        gateway.query("SELECT card_no FROM cards UNION ALL SELECT city FROM people", CONN)
    warned = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert [w.split(" holds")[0] for w in warned] == [
        "a computed result column over cards",
        "a computed result column over cards, people",
    ]


def test_verified_holds_in_labels_mode_and_through_a_table_alias(
    make_gateway: GatewayFactory, world: World
) -> None:
    gateway = make_gateway(VERIFIED + "web_enabled: false\n")
    out = gateway.query(
        "SELECT c.card_no, d.card_no AS other FROM cards c JOIN cards d ON d.holder = c.holder",
        CONN,
    )
    assert CARD_NO in json.dumps(out)
    assert _audit(world)[0]["masked"] == []


def test_an_answer_without_suspects_audits_an_empty_list(
    make_gateway: GatewayFactory, world: World
) -> None:
    make_gateway("").query("SELECT id FROM people", CONN)
    assert _audit(world)[0]["masked"] == []


def test_verified_does_not_cover_a_star_in_a_union(
    make_gateway: GatewayFactory, world: World
) -> None:
    out = make_gateway(VERIFIED).query(
        "SELECT * FROM cards UNION ALL SELECT card_no, holder FROM cards", CONN
    )
    assert CARD_NO not in json.dumps(out)
    if "error" not in out:
        assert _audit(world)[0]["masked"] == ["a computed result column over cards: card"]


def test_the_mask_link_opens_the_cells_own_value(make_gateway: GatewayFactory) -> None:
    gateway = make_gateway("")
    masked = _cells(gateway.query("SELECT card_no FROM cards", CONN))[1]
    match = MASK_LINK.fullmatch(str(masked))
    assert match is not None
    assert gateway._suspects._masks.reveal(match.group(1)) == CARD_NO  # noqa: SLF001
