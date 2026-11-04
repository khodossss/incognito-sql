"""The invented world: deterministic, canaries in every column class, a loadable declaration."""

import random
import re
from pathlib import Path

import pytest

from bench.canary import DIGIT_WINDOW, WINDOW, CanaryMint
from bench.oracle import leaks
from bench.ruled import HIDDEN_KEYS
from bench.schema import DIALECTS
from bench.world import World, generate_world
from incognito_sql.core.config import load_declaration

CANARY = re.compile(r"zq(?:[0189][g-z]){5}")
TYPED = ("amount", "amount_b", "born", "seen_at", "seen_tz", "cash", "huge", "unsigned_no", "mood")


def test_same_seed_same_world() -> None:
    assert generate_world(7) == generate_world(7)
    assert generate_world(7) != generate_world(8)


def test_every_hidden_class_carries_canaries(world: World) -> None:
    by_class: dict[str | None, set[str]] = {}
    for table in world.tables:
        for i, column in enumerate(table.columns):
            cells = " ".join(str(row[i]) for row in table.rows)
            by_class.setdefault(column.cls, set()).update(CANARY.findall(cells.casefold()))
    assert {k for k, v in by_class.items() if v} == {
        "identifier",
        "quasi",
        "open",
        "free_text",
        "secret",
        None,
    }
    assert by_class["quasi"] | by_class["open"] == {c.casefold() for c in world.visible}
    hidden = by_class["identifier"] | by_class["free_text"] | by_class["secret"] | by_class[None]
    assert hidden == {c.casefold() for c in world.forbidden if c.startswith("Zq")}


def test_typed_identifiers_carry_matchable_canaries(world: World) -> None:
    [ledger] = [t for t in world.tables if t.name == "ledger"]
    names = [c.name for c in ledger.columns]
    for column in TYPED:
        assert ledger.columns[names.index(column)].cls == "identifier"
        for row in ledger.rows:
            assert leaks(str(row[names.index(column)]), world.forbidden), column


def test_numeric_canaries_have_unique_signal_windows(world: World) -> None:
    numeric = [c for c in world.forbidden if c.isdigit()]
    windows = [c[i : i + DIGIT_WINDOW] for c in numeric for i in range(len(c) - DIGIT_WINDOW + 1)]
    assert len(windows) == len(set(windows))
    assert all(set(w) & set("0189") for w in windows)  # a tk_ token never holds these digits


def test_no_two_canaries_share_a_window() -> None:
    mint = CanaryMint(random.Random(1))  # noqa: S311 -- not a secret
    canaries = [mint.hidden() for _ in range(150)] + [mint.visible() for _ in range(10)]
    windows = [c.casefold()[i : i + WINDOW] for c in canaries for i in range(len(c) - WINDOW + 1)]
    assert len(windows) == len(set(windows))


@pytest.mark.parametrize("dialect", DIALECTS)
def test_declaration_loads_and_hides_undeclared(world: World, tmp_path: Path, dialect: str) -> None:
    path = tmp_path / "bench.yaml"
    path.write_text(world.declaration(dialect, web=False), encoding="utf-8")
    decl = load_declaration(path)
    assert decl.web_enabled is False
    assert "ssn" not in decl.columns["users"]
    assert "vault" not in decl.columns
    assert decl.columns["users"]["password_hash"] == "secret"  # noqa: S105 -- a class
    assert decl.columns["ledger"]["odd name"] == "open"
    assert ("cash" in decl.columns["ledger"]) == (dialect == "tsql")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_statements_cover_every_table(world: World, dialect: str) -> None:
    statements = world.statements(dialect)
    types = 1 if dialect in {"postgres", "duckdb"} else 0  # the user-defined ENUM
    assert len(statements) == 2 * len(world.stored) + types
    assert all(s.startswith(("CREATE TABLE ", "INSERT INTO ", "CREATE TYPE ")) for s in statements)
    assert world.planted(dialect) <= world.forbidden


def test_rules_on_rows_hide_their_own_canaries_and_keys(world: World) -> None:
    [patients] = [t for t in world.ruled if t.name == "patients"]
    assert not {t.name for t in world.ruled} & {t.name for t in world.tables}
    hidden = {str(row[2]) for row in patients.rows if row[0] in HIDDEN_KEYS["patients"]}
    assert hidden == set(world.row_hidden)
    assert len(world.row_hidden) == 2  # the ward of patients 3 and 4
    assert world.gateway_hidden == world.forbidden | world.row_hidden
    assert not world.row_hidden & world.forbidden


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_declaration_loads_with_its_rules(world: World, dialect: str, tmp_path: Path) -> None:
    config = tmp_path / "decl.yaml"
    config.write_text(world.declaration(dialect, web=False), encoding="utf-8")
    decl = load_declaration(config)
    assert {e.table for e in decl.entities} == {"users", "patients"}
    assert [r.where for r in decl.row_rules] == ["id = 4", "id = 3"]
