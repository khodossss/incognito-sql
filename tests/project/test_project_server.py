"""The project server: setup through its tools, no restart, nothing secret in its answers."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from incognito_sql.project import actions, dsn
from incognito_sql.project.live import Live
from incognito_sql.project.place import FOLDER, Place
from incognito_sql.project.tools import Tools

KEY = bytes(range(32))
NAMES = ("Mira Quellbrandt", "Oskar Vennholm", "Ilse Marrowind", "Tobin Arcwright")


def _tools(root: Path, environ: dict[str, str] | None = None) -> tuple[Tools, Live, list[str]]:
    place, opened = Place(root), list[str]()
    live = Live(place, lambda n, f: dsn.find(n, f, environ or {}, lambda _: None), lambda: KEY)

    def browser(url: str) -> bool:
        opened.append(url)
        return True

    tools = Tools(place, live, "9.9.9", open_browser=browser)
    return tools, live, opened


def _read(text: str) -> dict[str, object]:
    data = json.loads(text)
    assert isinstance(data, dict)
    return data


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    return root


def test_an_empty_project_says_how_to_begin(project: Path) -> None:
    tools, live, _ = _tools(project)
    status = _read(tools.status())
    assert status["ready"] is False
    assert "create_demo" in str(status["next"])
    assert 'uvx "incognito-sql==9.9.9" secret SHOP_DSN' in str(status["next"])
    assert _read(tools.query("SELECT 1", "c1"))["error"] == "not_set_up"
    live.close()


def test_the_demo_is_set_up_and_answered_without_a_restart(project: Path) -> None:
    # An older demo's DSN in the environment under the same name must not win.
    tools, live, opened = _tools(project, {actions.DEMO_DSN: "sqlite:///elsewhere.db"})
    made = _read(tools.create_demo())
    assert Path(str(made["declaration"])) == project / FOLDER / "config.yaml"
    assert (project / FOLDER / ".gitignore").read_text().strip().endswith("*")
    status = _read(tools.status())
    assert status["ready"] is True
    assert status["dsn_found_in"] == dsn.PROJECT
    assert status["protection"] == "permissive"  # shown, so the agent can name it
    assert status["human_sees_more"] is True  # identifier columns: the cards are offered
    assert "offer to sign them in" in str(status["next"])
    sql = (
        "SELECT c.full_name, SUM(o.total) AS spent FROM customers c JOIN orders o "
        "ON o.customer_id = c.id GROUP BY c.id, c.full_name ORDER BY spent DESC LIMIT 1"
    )
    answer = tools.query(sql, "c1")
    assert "320.5" in answer
    assert not any(name in answer for name in NAMES)
    assert "tk_" in answer
    cards = _read(tools.open_cards())
    assert cards["opened"] is True
    assert "/login/" in opened[0]
    assert "/login/" not in json.dumps(cards)  # the sign-in code never reaches the model
    assert "demo" in str(_read(tools.create_demo())["error"])  # a second demo would replace it
    live.close()


def test_a_database_file_is_drafted_and_an_edit_is_taken_at_once(project: Path) -> None:
    db = project / "clinic.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE patients (id INTEGER PRIMARY KEY, full_name TEXT, city TEXT)")
        con.execute("INSERT INTO patients VALUES (1, 'Halvi Elsby', 'Brindle')")
    con.close()
    tools, live, _ = _tools(project)
    draft = _read(tools.draft("sqlite", database_file="clinic.db"))  # relative: the project's
    assert draft["written"] is True
    assert "Halvi" not in json.dumps(draft)  # sampled, never returned
    assert "patients.full_name" in json.dumps(draft["candidates"])
    config = project / FOLDER / "config.yaml"
    text = config.read_text(encoding="utf-8")
    assert "web_port:" in text
    decided = (
        "dsn_env: INCOGNITO_DB_DSN\ndialect: sqlite\n"
        f"web_port: {text.split('web_port: ')[1].strip()}\n"
        "columns:\n  patients:\n    id: open\n    full_name: identifier\n    city: quasi\n"
        "entities:\n  - table: patients\n    pk: id\n"
    )
    config.write_text(decided, encoding="utf-8")
    first = tools.query("SELECT full_name, city FROM patients", "c1")
    assert "Brindle" in first
    assert "Halvi" not in first
    stamp = config.stat().st_mtime_ns
    config.write_text(decided.replace("city: quasi", ""), encoding="utf-8")
    os.utime(config, ns=(stamp + 10**9, stamp + 10**9))
    assert _read(tools.query("SELECT city FROM patients", "c1"))["error"]  # now hidden
    again = _read(tools.draft("sqlite", database_file=str(db)))
    assert again["written"] is False  # the human's declaration is never overwritten
    live.close()


def test_a_server_database_waits_for_the_human_s_variable(project: Path) -> None:
    tools, live, _ = _tools(project)
    refused = _read(tools.draft("postgres", dsn_env="SHOP_DSN"))
    assert "secret" in str(refused["error"])
    assert "dsn_env takes" in str(_read(tools.draft("postgres", dsn_env="postgres://x"))["error"])
    live.close()


def test_the_dsn_is_found_by_name_in_order(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    assert dsn.find("X_DSN", env, {}, lambda _: "u") == dsn.Found("u", dsn.USER)
    assert dsn.find("X_DSN", env, {"X_DSN": "e"}, lambda _: "u") == dsn.Found("e", dsn.ENVIRONMENT)
    dsn.keep(env, "X_DSN", "p")
    dsn.keep(env, "X_DSN", "q")  # replaced, not repeated
    assert env.read_text(encoding="utf-8") == "X_DSN=q\n"
    assert dsn.find("X_DSN", env, {"X_DSN": "e"}, lambda _: "u") == dsn.Found("q", dsn.PROJECT)
    assert dsn.find("Y_DSN", env, {}, lambda _: None) is None


def test_the_project_is_the_one_the_client_names(tmp_path: Path) -> None:
    assert Place.of({"CLAUDE_PROJECT_DIR": str(tmp_path)}, Path("elsewhere")).root == tmp_path
    assert Place.of({}, tmp_path).root == tmp_path


def test_a_taken_port_moves_on(tmp_path: Path) -> None:
    place = Place(tmp_path)
    first = place.first_port()
    assert actions.free_port(place, lambda port: port == first) != first
    with pytest.raises(actions.ActionError):
        actions.free_port(place, lambda _: True)
