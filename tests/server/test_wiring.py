"""The files a config owns: the token store and the audit log, named next to it."""

from pathlib import Path

from incognito_sql.core.pipeline import Gateway
from incognito_sql.wiring import audit_path, store_path

from .conftest import World


def test_files_sit_next_to_the_config(tmp_path: Path) -> None:
    config = tmp_path / "shop.yaml"
    assert audit_path(config) == tmp_path / "shop.audit.jsonl"
    assert store_path(config) == tmp_path / "shop.tokens.db"


def test_the_gateway_appends_to_its_audit_path(gateway: Gateway, world: World) -> None:
    gateway.query("SELECT id FROM people", "c1")
    assert world.audit == audit_path(world.config)
    assert len(audit_path(world.config).read_text("utf-8").splitlines()) == 1
