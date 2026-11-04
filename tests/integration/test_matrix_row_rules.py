"""Row rules on all five DBMS: the masked copy of a table parses and runs everywhere."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from bench.dbms import Database, load
from incognito_sql.core.config import load_declaration
from incognito_sql.wiring import open_gateway

from .conftest import CONFIG, KEY, Field
from .test_matrix import rows, token

pytestmark = pytest.mark.integration

RULES = (
    "row_rules:\n"
    "  - {table: people, hide: [city, full_name], where: 'id = 1'}\n"
    "  - {table: orders, hide: '*', where: 'amount > 200'}\n"
)


def test_hidden_cells_and_rows(field: Field) -> None:
    gw = field.open(RULES)
    cities = gw.query(field.sql("SELECT id, city FROM people ORDER BY id"), "c1")
    assert rows(cities) == [[1, None], [2, "Haifa"], [3, "Eilat"]]
    named = gw.query(field.sql("SELECT id FROM people WHERE full_name = 'Ivan Petrov'"), "c1")
    assert rows(named) == []
    counted = gw.query(field.sql("SELECT count(*) FROM orders"), "c1")
    joined = gw.query(
        field.sql("SELECT count(*) FROM orders o JOIN people p ON o.person_id = p.id"), "c1"
    )
    assert rows(counted) == rows(joined) == [[2]]  # order 11 (amount 250) is gone


LABELS = "web_enabled: false\n"
NO_THREE = "row_rules: [{table: people, hide: '*', where: 'id = 3'}]\n"


def _people_keys(field: Field, extra: str) -> list[object]:
    gw = field.open(LABELS + extra)
    answer = gw.query(field.sql("SELECT customer_name FROM orders WHERE id = 11"), "c1")
    labels = answer["labels"]
    assert isinstance(labels, dict), answer
    return [key for keys in labels.values() for key in keys.get("people", [])]


def test_a_label_gives_no_key_of_a_hidden_row(field: Field) -> None:
    assert 3 in _people_keys(field, "")  # the control: the key shows without the rule
    assert 3 not in _people_keys(field, NO_THREE)


NO_BIG_ORDERS = "row_rules: [{table: orders, hide: '*', where: 'amount > 200'}]\n"


def test_a_condition_that_can_fail_on_a_dropped_row_is_refused(field: Field) -> None:
    gw = field.open(NO_BIG_ORDERS)
    failing = gw.query(field.sql("SELECT count(*) FROM orders WHERE 1 / (amount - 250) > -1"), "c1")
    assert failing["error"] == "hidden_rows"  # order 11 (amount 250) would divide by zero
    computed = gw.query(field.sql("SELECT id, amount * 2 FROM orders"), "c1")
    assert computed["error"] == "hidden_rows"  # wherever it stands
    summed = gw.query(field.sql("SELECT count(*), sum(amount) FROM orders"), "c1")
    assert len(rows(summed)) == 1  # an aggregate reads only the rows kept


PARTED = (
    "CREATE TABLE rr_parted (id integer, who text) PARTITION BY RANGE (id)",
    (
        "CREATE TABLE rr_parted_low PARTITION OF rr_parted FOR VALUES FROM (0) TO (100)"
        " PARTITION BY RANGE (id)"
    ),
    "CREATE TABLE rr_parted_old PARTITION OF rr_parted_low FOR VALUES FROM (0) TO (50)",
    "CREATE TABLE rr_people_more () INHERITS (people)",
    "INSERT INTO rr_parted VALUES (1, 'Lior Zek'), (2, 'Tami Oren')",  # both in rr_parted_old
)
READERS = (
    "  rr_parted: {id: open, who: identifier}\n"
    "  rr_parted_low: {id: open, who: identifier}\n"
    "  rr_parted_old: {id: open, who: identifier}\n"
    "  rr_people_more: {id: open, city: quasi}\n"
    "  orders: {id: open}\n"
)


def test_a_partition_or_child_of_a_ruled_table_is_named(
    postgres_backend: Database, tmp_path: Path
) -> None:
    admin = create_engine(postgres_backend.admin)
    try:
        load(postgres_backend, PARTED)  # the reader may SELECT the new tables too
        config = tmp_path / "field.yaml"
        base = CONFIG.format(dialect="postgres").replace(
            "  orders: {id: open, person_id: open, customer_name: identifier, amount: open}\n",
            READERS,
        )
        on_parents = (
            "row_rules:\n"
            "  - {table: rr_parted, hide: [who], where: 'id = 1'}\n"
            "  - {table: people, hide: [city], where: 'id = 1'}\n"
        )
        on_children = (  # a parent reads its children's rows, at any depth
            "row_rules:\n"
            "  - {table: rr_parted_old, hide: [who], where: 'id = 1'}\n"
            "  - {table: rr_people_more, hide: [city], where: 'id = 1'}\n"
        )
        same = "".join(
            f"  - {{table: {t}, hide: [who], where: 'id = 1'}}\n"
            for t in ("rr_parted", "rr_parted_low", "rr_parted_old")
        )
        stricter = "  - {table: rr_parted_old, hide: [who], where: 'id = 2'}\n"
        for rules, extra, named in (
            (on_parents, "", ["rr_parted_low", "rr_parted_old", "rr_people_more"]),
            (
                on_parents,
                "verified_relations: [rr_parted_low, rr_parted_old, rr_people_more]\n",
                [],
            ),
            (on_children, "", ["people", "rr_parted", "rr_parted_low"]),
            ("row_rules:\n" + same, "", []),  # one family, the same rules: it starts
            # a partition's own rule more: reading the parent would skip it
            ("row_rules:\n" + same + stricter, "", ["rr_parted", "rr_parted_low"]),
        ):
            config.write_text(base + rules + extra, encoding="utf-8")
            gw = open_gateway(config, load_declaration(config), postgres_backend.url, KEY)
            try:
                assert gw.unruled_readers() == named
                if rules == "row_rules:\n" + same:  # the parent shows its partition masked
                    found = sorted(rows(gw.query("SELECT id, who FROM rr_parted", "c1")))
                    assert [row[0] for row in found] == [1, 2]
                    assert found[0][1] is None
                    token(found[1][1])
            finally:
                gw.close()
    finally:
        with admin.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS rr_parted, rr_people_more"))
        admin.dispose()
