"""`assess` on every DBMS: its cuts and series are written in the DBMS's dialect and answered."""

from pathlib import Path

import pytest

from bench.dbms import Database
from incognito_sql.assess.model import Source
from incognito_sql.assess.report import as_dict
from incognito_sql.assess.run import assess
from incognito_sql.core.config import load_declaration

from .conftest import KEY

pytestmark = pytest.mark.integration
# One identifier column keeps the lifted series to a few thousand queries per DBMS; every
# other column of the world is hidden, and each of its cuts must be refused.
CONFIG = """
dsn_env: INCOGNITO_TEST_DSN
dialect: {dialect}
protection: {profile}
columns:
  people: {{id: open, full_name: identifier}}
entities:
  - {{table: people, pk: id}}
"""


def _assess(
    backend: Database, tmp_path: Path, profile: str, *, capacity: bool
) -> dict[str, list[dict[str, object]]]:
    config = tmp_path / "field.yaml"
    config.write_text(CONFIG.format(dialect=backend.dialect, profile=profile), encoding="utf-8")
    source = Source(config, load_declaration(config), backend.url, KEY)
    return as_dict(assess(source, count=1, capacity=capacity))


def test_strict_holds_and_every_hidden_column_is_refused(backend: Database, tmp_path: Path) -> None:
    report = _assess(backend, tmp_path, "strict", capacity=False)
    (name,) = report["columns"]
    assert name["column"] == "people.full_name"
    assert name["verdict"] == "holds"
    assert name["L1 cuts"] == "0/4"
    assert report["hidden"]
    assert {h["verdict"] for h in report["hidden"]} == {"holds"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["field.yaml"]  # its files: a copy


def test_permissive_with_the_budgets_lifted_reads_a_value_whole(
    backend: Database, tmp_path: Path
) -> None:
    report = _assess(backend, tmp_path, "permissive", capacity=True)
    (lifted,) = report["capacity"]
    # the prefix series ran in this DBMS's dialect to the value's end
    assert lifted["L1 series"] == "1/1"
    assert lifted["verdict"] == "holds"  # read whole with the budgets lifted: a measure
    assert lifted["hours whole"] not in {"-", "closed", "unlimited"}
