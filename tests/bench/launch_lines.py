"""Helpers for competitor tests: a tool's launch line without Docker, and the hidden columns."""

from pathlib import Path
from types import ModuleType

import pytest
from mcp import StdioServerParameters

from bench.adapters import launch
from bench.dbms import Database
from bench.world import World


def opened(module: ModuleType, db: Database, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Return the launch line of ``module``'s tool and how its image was asked for."""
    asked: dict[str, object] = {}
    monkeypatch.setattr("shutil.which", lambda name: name)
    monkeypatch.setattr(launch, "ensure_image", lambda tag, **kw: asked.update(kw) or tag)
    if hasattr(module, "StdioAdapter"):
        monkeypatch.setattr(module, "StdioAdapter", lambda *a, **_kw: asked.update(params=a[2]))
    module.open_adapter(db, Path("work"))
    params = asked.pop("params")
    assert isinstance(params, StdioServerParameters)
    return [*params.args, *(f"{k}={v}" for k, v in asked.items())]


def hidden_columns(world: World, dialect: str | None = None) -> dict[str, set[str]]:
    """Columns that carry hidden canaries (every class but open and quasi), on ``dialect``."""
    return {
        t.name: {
            c.name
            for c in t.columns
            if c.cls not in {"open", "quasi"}
            and c.name != "id"
            and (dialect is None or c.type_on(dialect))
        }
        for t in world.tables
        if t.name != "canary"
    }


def hidden_names(world: World, dialect: str) -> set[str]:
    """The names of the hidden columns on ``dialect``, whatever their table."""
    return set().union(*hidden_columns(world, dialect).values())
