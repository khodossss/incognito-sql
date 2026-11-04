"""A secrets file of KEY=VALUE lines fills the environment it does not already set."""

from pathlib import Path

import pytest

from incognito_sql.envfile import EnvFileError, load_env_file


def test_lines_fill_missing_variables(tmp_path: Path) -> None:
    path = tmp_path / "secrets.env"
    path.write_text(
        "# the service's secrets\n\nSHOP_DSN=sqlite:///C:/x.db\n"
        " INCOGNITO_SQL_KEY = 'abc=='\nTOKEN=\"t t\"\nEMPTY=\n",
        encoding="utf-8",
    )
    env: dict[str, str] = {"TOKEN": "already"}
    load_env_file(path, env)
    assert env == {
        "SHOP_DSN": "sqlite:///C:/x.db",
        "INCOGNITO_SQL_KEY": "abc==",
        "TOKEN": "already",
        "EMPTY": "",
    }


def test_a_byte_order_mark_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "secrets.env"
    path.write_text("\ufeffA=1\n", encoding="utf-8")
    env: dict[str, str] = {}
    load_env_file(path, env)
    assert env == {"A": "1"}


@pytest.mark.parametrize("line", ["no equals sign", "=value", "BAD KEY=1"])
def test_a_bad_line_names_its_number_not_its_text(tmp_path: Path, line: str) -> None:
    path = tmp_path / "secrets.env"
    path.write_text(f"A=1\n{line}\n", encoding="utf-8")
    with pytest.raises(EnvFileError) as caught:
        load_env_file(path, {})
    assert "line 2" in str(caught.value)
    assert line not in str(caught.value)


def test_an_unreadable_file_is_one_safe_line(tmp_path: Path) -> None:
    with pytest.raises(EnvFileError) as caught:
        load_env_file(tmp_path / "missing.env", {})
    assert "FileNotFoundError" in str(caught.value)
    assert "missing.env" not in str(caught.value)  # its path may be a pasted secret
