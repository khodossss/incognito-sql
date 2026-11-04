"""A secret pasted into the wrong argument is refused and never repeated."""

from pathlib import Path

import pytest

from incognito_sql.cli import main
from incognito_sql.connect.clients import valid_variable
from incognito_sql.demo import run_demo

DSN = "postgresql://shop:S3cretPw9@db.test/shop"
TOKEN = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # noqa: S105 -- a token's shape, invented
LONG = "MY_SUPER_SECRET_TOKEN_2026_PROD_X"  # an all-caps service token of 32+ characters


@pytest.fixture
def config(tmp_path: Path) -> str:
    assert run_demo(tmp_path) == 0
    return str(tmp_path / "shop.yaml")


@pytest.mark.parametrize(
    "argv",
    [
        ["connect", TOKEN, "--url", "http://127.0.0.1:8766/mcp"],
        ["connect", "codex", "--url", "http://127.0.0.1:8766/mcp", DSN],
        ["connect", "codex", "--config", DSN],
        ["connect", "codex", "--config", TOKEN],
        ["connect", "codex", "--url", "http://127.0.0.1:8766/mcp", "--name", DSN],
        ["connect", "codex", "--url", f"https://shop:{TOKEN}℀x@h.test/mcp"],
        ["connect", "codex", "--url", f"https://h.test:{TOKEN}/mcp"],
        ["connect", "codex", "--url", "http://127.0.0.1:8766/mcp", "--token-env", LONG],
    ],
)
def test_a_misplaced_secret_is_refused_and_not_repeated(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        raise SystemExit(main(argv))
    assert stopped.value.code == 2
    out = capsys.readouterr()
    for secret in (DSN, TOKEN, LONG, "S3cretPw9"):
        assert secret not in out.out + out.err, argv


def test_a_service_token_never_passes_as_its_variable() -> None:
    assert not valid_variable(LONG)
    assert valid_variable("INCOGNITO_SQL_MCP_TOKEN")


def test_the_demo_config_still_connects(config: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["connect", "codex", "--config", config]) == 0
    assert "[mcp_servers.shop]" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["connect", "codex", "--url", "http://127.0.0.1:8766/mcp", f"--write={TOKEN}"],
        ["init", f"--d={DSN}", "--dialect", "sqlite", "--out", "o.yaml"],
        ["connect", "codex", f"--={TOKEN}"],
        ["init", "--dsn-env", DSN, "--dialect", "sqlite", "--out", "o.yaml"],
        ["connect", "codex", "--url", f"https://admin:12345/{TOKEN}@db.test/mcp"],
        ["connect", "codex", "--url="],
        ["connect", f"{DSN} not allowed with argument", "--config", "x"],
        ["connect", f"the following arguments are required: {TOKEN}"],
        ["demo", "a", f"{DSN}"],
    ],
)
def test_round_four_inputs_are_refused_without_the_value(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:  # the parser exits; the commands return
        raise SystemExit(main(argv))
    assert stopped.value.code == 2
    out = capsys.readouterr()
    for secret in (DSN, TOKEN, "S3cretPw9"):
        assert secret not in out.out + out.err, argv


def test_check_names_files_by_their_argument(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "dsn.yaml"
    config.write_text(
        f"dsn_env: '{DSN}'\ndialect: sqlite\ncolumns:\n  t: {{id: open}}\n"
        "entities:\n  - {table: t, pk: id}\n",
        "utf-8",
    )
    main(["check", "--config", str(config), "--env-file", DSN])
    out = capsys.readouterr()
    assert "S3cretPw9" not in out.out + out.err
    assert "secrets file (--env-file)" in out.out


def test_a_value_from_an_almost_valid_config_is_not_repeated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(Path(config).read_text("utf-8") + "protection: Zq7SECRETpw\n", "utf-8")
    assert main(["connect", "codex", "--config", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "Zq7SECRETpw" not in err
    assert "invalid value" in err


def test_check_survives_a_dsn_that_does_not_parse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, config: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEMO_SHOP_DSN", "sqlite://u:pw@h:Zq7SECRETpw/x.db")
    main(["check", "--config", config])
    out = capsys.readouterr()
    assert "Zq7SECRETpw" not in out.out + out.err


@pytest.mark.usefixtures("config")  # the demo shop in tmp_path, for init to read
def test_a_pasted_path_is_not_repeated_in_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    blocker = tmp_path / "Zq7SECRETpw"
    blocker.write_text("a file, not a folder", "utf-8")
    assert main(["demo", str(blocker / "shop")]) == 1
    monkeypatch.setenv("DEMO_SHOP_DSN", f"sqlite:///{(tmp_path / 'shop.db').as_posix()}")
    assert (
        main(
            [
                "init",
                "--dsn-env",
                "DEMO_SHOP_DSN",
                "--dialect",
                "sqlite",
                "--out",
                str(blocker / "o.yaml"),
            ]
        )
        == 1
    )
    out = capsys.readouterr()
    assert "Zq7SECRETpw" not in out.out + out.err
    assert "cannot write the demo folder" in out.err
    assert "cannot write the --out file" in out.err


@pytest.mark.parametrize(
    "argv",
    [
        ["serve", "--config", "{}"],
        ["connect", "codex", "--config", "{}"],
        ["connect", "claude-code", "--config", "{}"],
        ["check", "--config", "{}"],
    ],
)
def test_a_token_in_place_of_dsn_env_is_not_repeated(
    argv: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str
) -> None:
    token = "dzq7secret0123456789abcdef012345"  # noqa: S105 -- a hex token's shape, invented
    bad = tmp_path / "token.yaml"
    bad.write_text(
        Path(config).read_text("utf-8").replace("dsn_env: DEMO_SHOP_DSN", f"dsn_env: {token}"),
        "utf-8",
    )
    main([a.replace("{}", str(bad)) for a in argv])
    out = capsys.readouterr()
    assert "zq7secret" not in out.out + out.err


@pytest.mark.parametrize(
    "line",
    [
        "limits: {max_rows: !!int Zq7SECRETpw}\n",
        "limits: {max_rows: !!float Zq7SECRETpw}\n",
        "web_enabled: !!bool Zq7SECRETpw\n",
        "columns: {customers: {'postgresql://shop:Zq7SECRETpw@h/x': bogus}}\n",
        "columns: {customers: {ghp_Zq7SECRETpw: bogus}}\n",  # a key shaped as a name
        "protections: {Zq7SECRETpw: {bogus: 1}}\n",
        "columns: {customers: {-4821397: open}}\n",
        "protection: Zq7SECRETpw\n",  # a validator's message
        "verified_open: {'Zq7SECRETpw:x': [a]}\n",
    ],
)
def test_a_value_typed_in_a_config_tag_or_key_is_not_repeated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, line: str
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(Path(config).read_text("utf-8") + line, "utf-8")
    assert main(["connect", "codex", "--config", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "zq7secretpw" not in err.lower()
    assert "cannot read the config" in err
    assert main(["diff", config, str(bad)]) == 2  # diff reads it too
    err = capsys.readouterr().err
    assert "zq7secretpw" not in err.lower()
    assert "cannot read the new declaration" in err
