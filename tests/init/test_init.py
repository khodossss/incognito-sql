"""`init`: name hints, scaffold, contradictions and the no-leak guarantee."""

import sqlite3
from pathlib import Path

import pytest

from incognito_sql.cli import main
from incognito_sql.core.config import Declaration, load_declaration
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.init.hints import NAME_HINTS, name_hint
from incognito_sql.init.report import contradictions
from incognito_sql.init.scaffold import scaffold

ENV = "INCOGNITO_INIT_DSN"
PHONES = ["+972 50 123 4567", "+972 52 765 4321"]
CATALOG = Catalog(
    columns={
        "people": {"id": "INTEGER", "full_name": "TEXT", "buyerPhone": "TEXT", "note": "TEXT"},
        "chats": {"whatsapp_id": "TEXT", "description": "TEXT"},
    }
)


def test_name_hints_verbatim() -> None:
    assert NAME_HINTS == (
        "name", "phone", "email", "mail", "nick", "passport", "address",
        "password", "ip", "city", "zip", "dob", "birth",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("column", "hint"),
    [
        ("full_name", "name"),
        ("buyer_phone", "phone"),
        ("buyerPhone", "phone"),
        ("birthdate", "birth"),
        ("zipcode", "zip"),
        ("zip", "zip"),
        ("email", "email"),
        ("ipaddr", "ip"),
        ("e_mail", "mail"),
    ],
)
def test_hint_matches_by_token(column: str, hint: str) -> None:
    assert name_hint(column) == hint


@pytest.mark.parametrize("column", ["description", "id", "whatsapp_id", "amount"])
def test_hint_does_not_match_inside_a_token(column: str) -> None:
    assert name_hint(column) is None


def test_scaffold_loads_and_hides_everything(tmp_path: Path) -> None:
    text = scaffold(CATALOG, None, dsn_env=ENV, dialect="sqlite")
    path = tmp_path / "decl.yaml"
    path.write_text(text, encoding="utf-8")
    decl = load_declaration(path)
    assert (decl.dsn_env, decl.dialect) == (ENV, "sqlite")
    assert all(not cols for cols in decl.columns.values())
    assert set(decl.columns) == {"people", "chats"}
    assert '  #   "full_name": identifier  # PII?: name hint "name"' in text
    assert '  #   "buyerPhone": identifier  # PII?: name hint "phone"' in text
    assert '  #   "note": open' in text
    assert '  #   "whatsapp_id": open' in text


def test_scaffold_marks_sampled_candidates() -> None:
    samples: dict[tuple[str, str], list[object]] = {("chats", "whatsapp_id"): [*PHONES]}
    text = scaffold(CATALOG, samples, dsn_env=ENV, dialect="sqlite")
    assert '  #   "whatsapp_id": identifier  # PII?: sample looks personal' in text
    assert PHONES[0] not in text


def test_contradictions_by_name_and_by_sample() -> None:
    decl = Declaration.model_validate(
        {
            "dsn_env": ENV,
            "dialect": "sqlite",
            "entities": [],
            "columns": {
                "people": {"full_name": "open", "id": "open", "city": "quasi"},
                "chats": {"whatsapp_id": "open", "description": "free_text"},
            },
        }
    )
    assert contradictions(decl, None) == ['people.full_name: name hint "name"']
    found = contradictions(decl, {("chats", "whatsapp_id"): [*PHONES]})
    assert "chats.whatsapp_id: sample looks personal" in found
    assert 'people.full_name: name hint "name"' in found
    assert not any(PHONES[0] in line for line in found)


def _db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, ref TEXT, note TEXT);
        INSERT INTO people VALUES (1, 'Zqcanary Person', 'zqcanary@example.com', 'ok');
        INSERT INTO people VALUES (2, 'Zqcanary Other', '+972 50 123 4567', 'fine');
        """
    )
    con.commit()
    con.close()


def test_init_writes_scaffold_and_leaks_no_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db, out = tmp_path / "w.db", tmp_path / "decl.yaml"
    _db(db)
    monkeypatch.setenv(ENV, f"sqlite:///{db.as_posix()}")
    code = main(["init", "--dsn-env", ENV, "--dialect", "sqlite", "--out", str(out)])
    seen = capsys.readouterr()
    assert code == 0
    written = out.read_text(encoding="utf-8")
    for channel in (seen.out, seen.err, written):
        assert "zqcanary" not in channel.lower()
        assert "123 4567" not in channel
    assert '  #   "ref": identifier  # PII?: sample looks personal' in written
    assert '  #   "note": open' in written
    assert str(out) in seen.out
    assert not load_declaration(out).entities


def test_init_without_sample_skips_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, out = tmp_path / "w.db", tmp_path / "decl.yaml"
    _db(db)
    monkeypatch.setenv(ENV, f"sqlite:///{db.as_posix()}")
    argv = ["init", "--dsn-env", ENV, "--dialect", "sqlite", "--no-sample", "--out", str(out)]
    assert main(argv) == 0
    written = out.read_text(encoding="utf-8")
    assert '  #   "ref": open' in written
    assert 'name hint "name"' in written


def test_init_on_existing_file_lists_contradictions_and_keeps_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db, out = tmp_path / "w.db", tmp_path / "decl.yaml"
    _db(db)
    body = (
        f"dsn_env: {ENV}\ndialect: sqlite\nentities: []\n"
        "columns:\n  people: {id: open, full_name: open, ref: open}\n"
    )
    out.write_text(body, encoding="utf-8")
    monkeypatch.setenv(ENV, f"sqlite:///{db.as_posix()}")
    code = main(["init", "--dsn-env", ENV, "--dialect", "sqlite", "--out", str(out)])
    seen = capsys.readouterr()
    assert code == 0
    assert out.read_text(encoding="utf-8") == body
    assert 'people.full_name: name hint "name"' in seen.out
    assert "people.ref: sample looks personal" in seen.out
    assert "zqcanary" not in (seen.out + seen.err).lower()


def test_init_missing_dsn_env_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(ENV, raising=False)
    out = tmp_path / "decl.yaml"
    code = main(["init", "--dsn-env", ENV, "--dialect", "sqlite", "--out", str(out)])
    assert code == 2
    assert "--dsn-env is not set" in capsys.readouterr().err
    assert not out.exists()


RESERVED = ["null", "on", "yes", "no", "off", "true", "false", "😀 tbl"]


def test_reserved_and_astral_names_round_trip(tmp_path: Path) -> None:
    catalog = Catalog(columns={name: {name: "TEXT", "x": "TEXT"} for name in RESERVED})
    path = tmp_path / "decl.yaml"
    path.write_text(scaffold(catalog, None, dsn_env="on", dialect="sqlite"), encoding="utf-8")
    decl = load_declaration(path)
    assert decl.dsn_env == "on"
    assert set(decl.columns) == set(RESERVED)


def test_uncommenting_a_column_gives_a_valid_mapping(tmp_path: Path) -> None:
    text = scaffold(CATALOG, None, dsn_env=ENV, dialect="sqlite")
    text = text.replace('  #   "note": open', '    "note": open')
    path = tmp_path / "decl.yaml"
    path.write_text(text, encoding="utf-8")
    decl = load_declaration(path)
    assert decl.columns["people"] == {"note": "open"}


def test_quasi_is_a_contradiction_only_by_value() -> None:
    decl = Declaration.model_validate(
        {
            "dsn_env": ENV,
            "dialect": "sqlite",
            "entities": [],
            "columns": {"chats": {"whatsapp_id": "quasi", "birth_date": "quasi"}},
        }
    )
    assert contradictions(decl, None) == []
    found = contradictions(decl, {("chats", "whatsapp_id"): [*PHONES]})
    assert found == ["chats.whatsapp_id: sample looks personal"]


def test_unsampled_column_is_marked_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db, out = tmp_path / "w.db", tmp_path / "decl.yaml"
    _db(db)
    con = sqlite3.connect(db)
    con.execute("CREATE VIEW broken AS SELECT abs(-9223372036854775808) AS x")
    con.commit()
    con.close()
    monkeypatch.setenv(ENV, f"sqlite:///{db.as_posix()}")
    assert main(["init", "--dsn-env", ENV, "--dialect", "sqlite", "--out", str(out)]) == 0
    written = out.read_text(encoding="utf-8")
    assert '  #   "x": open  # not sampled' in written
    assert written.count("# not sampled") == 1
    assert "1 column not sampled" in capsys.readouterr().out


def test_unwritable_out_path_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "w.db"
    _db(db)
    out = tmp_path / "missing" / "decl.yaml"
    monkeypatch.setenv(ENV, f"sqlite:///{db.as_posix()}")
    assert main(["init", "--dsn-env", ENV, "--dialect", "sqlite", "--out", str(out)]) == 1
    assert "cannot write" in capsys.readouterr().err


def test_missing_database_is_not_created_and_names_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "absent.db"
    monkeypatch.setenv(ENV, f"sqlite:///{db.as_posix()}")
    out = tmp_path / "decl.yaml"
    assert main(["init", "--dsn-env", ENV, "--dialect", "sqlite", "--out", str(out)]) == 1
    assert "cannot read the schema" in capsys.readouterr().err
    assert not db.exists()
    assert not out.exists()


def test_init_reads_the_dsn_from_an_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(ENV, raising=False)
    db, out, env = tmp_path / "w.db", tmp_path / "decl.yaml", tmp_path / "secrets.env"
    _db(db)
    env.write_text(f'{ENV}="sqlite:///{db.as_posix()}"\n', encoding="utf-8")
    argv = ["init", "--env-file", str(env), "--dsn-env", ENV, "--dialect", "sqlite"]
    assert main([*argv, "--out", str(out)]) == 0
    assert out.exists()
    missing = tmp_path / "zqcanary.env"
    assert main([*argv[:1], "--env-file", str(missing), *argv[3:], "--out", str(out)]) == 1
    assert "zqcanary" not in capsys.readouterr().err.lower()
