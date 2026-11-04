"""`incognito-sql try`: the verdict, the columns read, nothing run and nothing written."""

from pathlib import Path

import pytest

from incognito_sql.cli import main
from incognito_sql.core.tokens.store import TokenStore
from incognito_sql.mcp.refusals import GUIDE
from incognito_sql.trial import verdict as verdict_module

from .conftest import CANARY, DSN_ENV, World


def _try(world: World, sql: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["try", "--config", str(world.config), sql])
    out = capsys.readouterr()
    return code, out.out + out.err


def test_an_answered_query_shows_its_columns_and_output(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    code, text = _try(world, "SELECT full_name, city FROM people", capsys)
    assert code == 0
    assert "verdict: answered" in text
    assert "  people.full_name: identifier\n" in text
    assert "  people.city: quasi\n" in text
    assert "output columns: 1: pseudonym, 2: value" in text


def test_a_refusal_shows_its_code_retry_and_hint(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    code, text = _try(world, "SELECT secret_note FROM people", capsys)
    retry, hint = GUIDE["hidden_column"]
    assert code == 1
    assert f"verdict: refused: hidden_column (retry: {retry})" in text
    assert f"hint: {hint}" in text
    assert "output columns" not in text


@pytest.mark.parametrize(
    ("sql", "reads"),
    [
        (
            "SELECT p.full_name FROM orders o JOIN people p ON o.person_id = p.id",
            ["orders.person_id: open", "people.full_name: identifier", "people.id: open"],
        ),
        ("WITH x AS (SELECT city FROM people) SELECT city FROM x", ["people.city: quasi"]),
    ],
)
def test_base_columns_are_found_through_aliases_and_ctes(
    world: World, capsys: pytest.CaptureFixture[str], sql: str, reads: list[str]
) -> None:
    code, text = _try(world, sql, capsys)
    assert code == 0
    listed = [line.strip() for line in text.split("reads:\n")[1].splitlines() if line[:2] == "  "]
    assert listed == reads


def test_the_query_s_values_are_not_repeated_and_nothing_is_written(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    before = set(world.config.parent.iterdir())
    code, text = _try(world, "SELECT id FROM people WHERE full_name = 'Zqcanary Person'", capsys)
    assert code in {0, 1}
    assert CANARY not in text.lower()
    assert set(world.config.parent.iterdir()) == before  # no audit, no token store, no budget


def test_a_parse_error_reads_nothing(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, text = _try(world, "SELEC full_name FROM people", capsys)
    assert code == 1
    assert "verdict: refused: parse_error" in text
    assert "reads:" not in text


def test_without_a_database_nothing_is_tried(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DSN_ENV)
    code, text = _try(world, "SELECT 1", capsys)
    assert code == 2
    assert "dsn_env is not set" in text
    monkeypatch.setenv(DSN_ENV, "postgresql://u:Zqcanary@127.0.0.1:1/x")
    code, text = _try(world, "SELECT 1", capsys)
    assert code == 2
    assert "cannot read the schema" in text
    assert CANARY not in text.lower()


def test_a_bad_config_is_not_tried(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "bad.yaml"
    config.write_text("dialect: [\n", encoding="utf-8")
    assert main(["try", "--config", str(config), "SELECT 1"]) == 2
    assert "cannot read the config" in capsys.readouterr().err


def test_a_token_in_the_query_makes_the_answer_conditional(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    code, text = _try(
        world, "SELECT id FROM people WHERE full_name = 'tk_abcdefghijklmnop'", capsys
    )
    assert code == 0
    assert "verdict: answered if every token in it is live" in text


def test_a_probe_that_fails_midway_leaves_nothing_of_the_query(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    files: list[str] = []

    def failing(*args: object) -> None:
        store = args[2]
        assert isinstance(store, TokenStore)
        files.extend(row[2] for row in store._con.execute("PRAGMA database_list"))  # noqa: SLF001
        raise RuntimeError(CANARY)

    monkeypatch.setattr(verdict_module, "prepare", failing)
    before = set(world.config.parent.iterdir())
    code, text = _try(world, "SELECT id FROM people WHERE full_name = 'Zqcanary Person'", capsys)
    assert code == 2
    assert "the probe failed (RuntimeError)" in text
    assert CANARY not in text.lower()
    assert files == [""]  # SQLite's in-memory database: no file to leave behind
    assert set(world.config.parent.iterdir()) == before


def test_a_value_typed_into_a_wrong_slot_is_not_repeated(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    for argv in (
        ["try", "--config", "postgresql://u:Zqcanary@h/db", "SELECT 1"],
        ["try", "--config", str(world.config), "--env-file", "Zqcanary.env", "SELECT 1"],
    ):
        assert main(argv) == 2
        out = capsys.readouterr()
        assert CANARY not in (out.out + out.err).lower(), argv


def test_a_token_does_not_skip_the_check_of_the_rewritten_sql(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    sql = "SELECT full_name AS \"we ird\" FROM people WHERE full_name = 'tk_abcdefghijklmnop'"
    code, text = _try(world, sql, capsys)
    assert code == 1
    assert "verdict: refused: node_not_allowed" in text


def test_a_union_shows_its_output_columns(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    sql = "SELECT full_name, city FROM people UNION SELECT customer_name, 'x' FROM orders"
    code, text = _try(world, sql, capsys)
    assert code == 0
    assert "output columns: 1: pseudonym, 2: value" in text


def test_an_extra_argument_is_not_repeated(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:  # the parser exits; the command returns
        raise SystemExit(main(["try", "--config", str(world.config), "SELECT 1", CANARY]))
    assert stopped.value.code == 2
    out = capsys.readouterr()
    assert CANARY not in (out.out + out.err).lower()


def test_a_value_from_an_almost_valid_config_is_not_repeated(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(world.config.read_text("utf-8") + f"protection: {CANARY}\n", "utf-8")
    assert main(["try", "--config", str(bad), "SELECT 1"]) == 2
    err = capsys.readouterr().err
    assert CANARY not in err.lower()
    assert "invalid value" in err
