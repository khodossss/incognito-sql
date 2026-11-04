"""The demo: an invented SQLite database and a declaration that loads."""

import sqlite3
from contextlib import closing
from pathlib import Path

from bench.demo import main
from incognito_sql.core.config.load import load_declaration


def test_demo_writes_a_database_and_a_loadable_declaration(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 0
    with closing(sqlite3.connect(tmp_path / "demo.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    config = load_declaration(tmp_path / "demo.yaml")
    assert config.dsn_env == "DEMO_DSN"
