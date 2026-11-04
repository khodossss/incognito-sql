"""Column classes by who sees the value; the names before 0.1.2 still read."""

from pathlib import Path

from incognito_sql.core.config import ColumnClass, load_declaration

OLD = """dsn_env: X_DSN
dialect: sqlite
columns:
  people: {id: open, city: quasi, notes: free_text, password: secret, name: identifier}
entities: []
"""


def test_the_old_names_are_read_as_the_new_ones(tmp_path: Path) -> None:
    path = tmp_path / "old.yaml"
    path.write_text(OLD, encoding="utf-8")
    people = load_declaration(path).columns["people"]
    assert people["city"] is ColumnClass.QUASI
    assert people["notes"] is ColumnClass.FREE_TEXT
    assert people["password"] is ColumnClass.SECRET
    assert [c.value for c in ColumnClass] == [
        "identifier",
        "open_quasi",
        "closed",
        "closed_hidden",
        "open",
    ]


def test_the_new_names_load(tmp_path: Path) -> None:
    path = tmp_path / "new.yaml"
    text = OLD.replace("quasi", "open_quasi").replace("free_text", "closed")
    path.write_text(text.replace("secret", "closed_hidden"), encoding="utf-8")
    assert load_declaration(path).columns["people"]["notes"] is ColumnClass.FREE_TEXT
