from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from incognito_sql.core.config import Operation, column_operations, load_declaration
from incognito_sql.core.config.protection import (
    BASE,
    PRESETS,
    CustomProfile,
    Leak,
    opens,
    summary,
    warning,
)
from incognito_sql.core.config.report import protection_lines

Writer = Callable[..., Path]

COLUMNS = {"people": {"full_name": "identifier", "phone": "identifier", "id": "open"}}


def test_default_profile_is_permissive(write_yaml: Writer) -> None:
    decl = load_declaration(write_yaml())
    assert decl.protection == "permissive"
    assert column_operations(decl, "people", "full_name") == PRESETS["permissive"]


def test_presets_nest() -> None:
    assert PRESETS["strict"] == BASE
    assert PRESETS["balanced"] == BASE | {Operation.IS_NULL}
    assert PRESETS["permissive"] >= PRESETS["balanced"]


def test_custom_profile_extends_a_preset(write_yaml: Writer) -> None:
    decl = load_declaration(
        write_yaml(
            protections={"lean": {"extends": "balanced", "allow": ["is_null"], "deny": ["group"]}},
            protection="lean",
        )
    )
    ops = column_operations(decl, "people", "full_name")
    assert Operation.IS_NULL in ops
    assert Operation.GROUP not in ops
    assert Operation.OUTPUT in ops


def test_column_profile_overrides_the_database_profile(write_yaml: Writer) -> None:
    decl = load_declaration(
        write_yaml(columns=COLUMNS, column_protection={"People": {"PHONE": "strict"}})
    )
    assert column_operations(decl, "people", "phone") == PRESETS["strict"]
    assert column_operations(decl, "people", "full_name") == PRESETS["permissive"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"protection": "lax"},
        {"protections": {"strict": {"extends": "balanced"}}},
        {"protections": {"a": {"extends": "b"}, "b": {"extends": "strict"}}},
        {"protections": {"a": {"extends": "strict", "allow": ["bogus_op"]}}},
        {"protections": {"a": {"extends": "strict", "bogus": []}}},
        {"column_protection": {"people": {"id": "strict"}}},
        {"column_protection": {"people": {"notes": "strict"}}},
        {"column_protection": {"people": {"phone": "lax"}}},
    ],
)
def test_bad_protection_is_a_load_error(write_yaml: Writer, overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        load_declaration(write_yaml(columns=COLUMNS, **overrides))


def test_what_the_presets_open() -> None:
    assert opens(PRESETS["strict"]) == [Leak.EXISTENCE]
    assert Leak.LENGTH in opens(PRESETS["permissive"])
    assert opens(frozenset({Operation.OUTPUT, Operation.IS_NULL})) == []


def test_summary_names_what_is_open() -> None:
    line = summary("balanced", BASE)
    assert line.startswith("protection: balanced")
    assert "L3 existence" in line
    assert "opens nothing" in summary("x", frozenset({Operation.OUTPUT}))


def test_warning_for_what_follows_permissive() -> None:
    assert warning("strict", {}) is None
    assert warning("balanced", {}) is None
    assert warning("lean", {"lean": CustomProfile(extends="balanced")}) is None
    for name, custom in (
        ("permissive", {}),
        ("wide", {"wide": CustomProfile(extends="permissive")}),
    ):
        text = warning(name, custom)
        assert text is not None
        assert "follows permissive" in text
        assert "protection: balanced" in text


def test_a_profile_past_balanced_names_the_slow_channel(write_yaml: Writer) -> None:
    wide = protection_lines(load_declaration(write_yaml(limits={"literal_budget": 7})))
    [series] = [line for line in wide if "slow channel" in line]
    assert "7 literals and 100 probes in each 3600 s window" in series
    narrow = protection_lines(load_declaration(write_yaml(protection="balanced")))
    assert not [line for line in narrow if "slow channel" in line]
    ordered = load_declaration(
        write_yaml(
            protection="balanced",
            column_protection={"people": {"full_name": "permissive"}},
        )
    )
    assert [line for line in protection_lines(ordered) if "slow channel" in line]


def test_an_unlimited_budget_is_said_at_start(write_yaml: Writer) -> None:
    lines = protection_lines(
        load_declaration(write_yaml(protection="strict", limits={"literal_budget": "unlimited"}))
    )
    assert [line for line in lines if "limits.literal_budget is unlimited" in line]
    assert not [line for line in lines if "probe_budget is unlimited" in line]
    wide = protection_lines(load_declaration(write_yaml(limits={"probe_budget": "unlimited"})))
    assert [line for line in wide if "limits.probe_budget is unlimited" in line]
    assert [line for line in wide if "20 literals and unlimited probes" in line]


def test_column_protection_names_differing_only_in_case(write_yaml: Writer) -> None:
    clash = {"people": {"phone": "strict", "PHONE": "balanced"}}
    with pytest.raises(ValidationError):
        load_declaration(write_yaml(columns=COLUMNS, column_protection=clash))
    tables = {"people": {"phone": "strict"}, "PEOPLE": {"full_name": "strict"}}
    with pytest.raises(ValidationError):
        load_declaration(write_yaml(columns=COLUMNS, column_protection=tables))


def test_claims_name_what_each_preset_opens() -> None:
    from incognito_sql.core.config.protection import claims  # noqa: PLC0415

    found = claims()
    assert found["strict"] == ["L3 existence"]
    assert found["balanced"] == ["L3 existence"]
    assert set(found["permissive"]) == {
        "L3 existence",
        "L3 length",
        "L3 order",
        "L3 prefix",
        "L3 contains",
    }
