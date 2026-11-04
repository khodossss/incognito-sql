"""`audit verify` on the log a real gateway writes: holds, then names the edited line."""

import json
from pathlib import Path

import pytest

from incognito_sql.cli import main
from incognito_sql.core import audit
from incognito_sql.core.pipeline import Gateway

from .conftest import World

CONN = "c1"


def test_verify_holds_then_names_an_edit_without_quoting_it(
    gateway: Gateway, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    gateway.query("SELECT id FROM people WHERE full_name = 'Zqcanary Person'", CONN)
    gateway.query("SELECT secret_note FROM people", CONN)
    gateway.query("SELECT id FROM people", CONN)
    args = ["audit", "verify", "--config", str(world.config)]
    assert main(args) == 0
    assert capsys.readouterr().out.endswith("the chain holds\n")
    lines = world.audit.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace("hidden_column", "parse_error")
    Path(world.audit).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    assert main(args) == 1
    out = capsys.readouterr().out
    assert "broken: line 2 or 3: edited" in out
    assert "parse_error" not in out
    assert "secret_note" not in out


class _BeforeProbes:
    """``json`` as the audit log used it before lines carried ``probes``."""

    @staticmethod
    def dumps(entry: dict[str, object], **kw: object) -> str:
        return json.dumps({k: v for k, v in entry.items() if k != "probes"}, **kw)  # type: ignore[arg-type]


def test_a_log_begun_before_lines_carried_probes_still_holds(
    gateway: Gateway, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as old:
        old.setattr(audit, "json", _BeforeProbes)
        gateway.query("SELECT id FROM people WHERE full_name > 'M'", CONN)
        gateway.query("SELECT secret_note FROM people", CONN)
    gateway.query("SELECT id FROM people WHERE full_name > 'M'", CONN)
    lines = [json.loads(x) for x in world.audit.read_text(encoding="utf-8").splitlines()]
    assert ["probes" in x for x in lines] == [False, False, True]
    assert main(["audit", "verify", "--config", str(world.config)]) == 0


def test_a_line_longer_than_any_tail_keeps_the_chain(gateway: Gateway, world: World) -> None:
    # every column qualified by a long alias: one answered query, one audit line of ~80 KiB
    columns, alias = ",".join(["id"] * 400), "a" * 200
    sql = f"SELECT {columns} FROM people AS {alias}"  # noqa: S608 -- the model's query
    assert "rows" in gateway.query(sql, CONN)
    gateway.query("SELECT id FROM people", CONN)
    lines = world.audit.read_text(encoding="utf-8").splitlines()
    assert len(lines[0]) > 1 << 16
    assert [json.loads(x)["n"] for x in lines] == [0, 1]
    assert main(["audit", "verify", "--config", str(world.config)]) == 0
