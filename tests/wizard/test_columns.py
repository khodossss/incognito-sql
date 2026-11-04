"""The columns screen over a scaffold: take init's suggestion, change some, name the people."""

from pathlib import Path

import pytest

from incognito_sql.core.config import load_declaration
from incognito_sql.wizard import columns
from incognito_sql.wizard.columns import NotWritten, decide

from .conftest import Script

SCAFFOLD = """\
dsn_env: "SHOP_DSN"
dialect: "sqlite"
columns:
  "customers":
  #   "id": open
  #   "full_name": identifier  # PII?: name hint "name"
  #   "city": quasi  # PII?: name hint "city"
  "orders":
  #   "id": open
  #   "total": open
entities: []
"""


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "shop.yaml"
    path.write_text(SCAFFOLD, encoding="utf-8")
    return path


def test_taking_the_suggestions_writes_them_and_the_people(config: Path) -> None:
    script = Script("y", "y", "", "")  # both tables as suggested; customers; key id
    lines = decide(config, script.terminal())
    assert "customers.full_name: identifier" in lines
    decl = load_declaration(config)
    assert decl.columns["customers"]["full_name"].value == "identifier"
    assert [(e.table, e.pk) for e in decl.entities] == [("customers", "id")]
    assert 'PII? name hint "name"' in script.text()


def test_a_changed_column_and_a_hidden_one(config: Path) -> None:
    # customers: change 2 to free_text and 3 to hidden; orders as suggested; no people
    script = Script("n", "2-3", "free_text", "hidden", "y", "")
    decide(config, script.terminal())
    decl = load_declaration(config)
    assert decl.columns["customers"]["full_name"].value == "free_text"
    assert "city" not in decl.columns["customers"]
    assert decl.entities == []


def test_a_declaration_that_does_not_load_is_decided_again_or_given_up(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(columns, "apply_classes", lambda *_: "entities: bad key")
    script = Script("y", "y", "", "", "n")
    with pytest.raises(NotWritten):
        decide(config, script.terminal())
    assert "does not load: entities: bad key" in script.text()
    assert config.read_text(encoding="utf-8") == SCAFFOLD
