"""Value and person cards: declared columns only, escaped, current rows, budget alarm."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from incognito_sql.core.errors import Rejection

from .conftest import Parts

NO_ROWS = "no rows hold this value now"
HIDDEN = ("Zzhash1", "Zznote1", "pw_hash", "note")


def _token(parts: Parts, value: str = "Ivan Petrov", at: datetime | None = None) -> str:
    return parts.store.tokenize(value, at or datetime.now(UTC))


def test_value_card_shows_the_value_and_its_people(
    client: TestClient, parts: Parts, cookie: dict[str, str]
) -> None:
    token = _token(parts, "IVAN PETROV")  # the first spelling seen is the one shown
    assert _token(parts) == token  # the spelling stored in the row is a known variant
    page = client.get(f"/v/{token}", headers=cookie)
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    text = page.text
    assert "IVAN PETROV" in text
    assert "Ivan Petrov" in text  # the current row, found through the variant
    assert "Haifa" in text
    assert 'href="/p/people/1"' in text
    assert NO_ROWS not in text
    for hidden in HIDDEN:
        assert hidden not in text


def test_a_deleted_row_leaves_the_value_alone(
    client: TestClient, parts: Parts, cookie: dict[str, str]
) -> None:
    token = _token(parts)
    con = sqlite3.connect(parts.db)
    con.execute("DELETE FROM people WHERE id = 1")
    con.commit()
    con.close()
    text = client.get(f"/v/{token}", headers=cookie).text
    assert "Ivan Petrov" in text
    assert NO_ROWS in text


def test_a_token_expired_for_the_model_still_opens(
    client: TestClient, parts: Parts, cookie: dict[str, str]
) -> None:
    token = _token(parts, at=datetime.now(UTC) - timedelta(days=3))
    page = client.get(f"/v/{token}", headers=cookie)
    assert page.status_code == 200
    assert "Ivan Petrov" in page.text


@pytest.mark.parametrize(
    "path", ["/v/tk_zzzzzzzzzzzzzzzz", "/v/zzbogus", "/p/zzentity/1", "/p/people/999"]
)
def test_unknown_is_404_without_echo(client: TestClient, cookie: dict[str, str], path: str) -> None:
    response = client.get(path, headers=cookie)
    assert response.status_code == 404
    assert "zz" not in response.text
    assert "999" not in response.text
    assert "the setup that gave it" in response.text  # says why, not just "not found"


@pytest.mark.parametrize("path", ["/p/people/Zzabc", "/p/orders/Ivan%20Petrov"])
def test_bad_key_or_identifier_key_is_404(
    client: TestClient, cookie: dict[str, str], path: str
) -> None:
    response = client.get(path, headers=cookie)
    assert response.status_code == 404
    assert "Zzabc" not in response.text
    assert "Ivan" not in response.text


def test_person_card_has_declared_columns_but_no_secret(
    client: TestClient, cookie: dict[str, str]
) -> None:
    page = client.get("/p/people/1", headers=cookie)
    assert page.status_code == 200
    for shown in ("Ivan Petrov", "Haifa", "likes chess", "full_name", "city", "bio"):
        assert shown in page.text
    for hidden in HIDDEN:
        assert hidden not in page.text


def test_values_are_escaped(client: TestClient, parts: Parts, cookie: dict[str, str]) -> None:
    for path in ("/p/people/2", f"/v/{_token(parts, 'Anna <b>Ivanova</b>')}"):
        text = client.get(path, headers=cookie).text
        assert "Anna &lt;b&gt;Ivanova&lt;/b&gt;" in text
        assert "<b>Ivanova" not in text


def test_budget_alarm_shows_a_plaque(
    client: TestClient, parts: Parts, cookie: dict[str, str]
) -> None:
    assert 'class="alarm"' not in client.get("/", headers=cookie).text
    with pytest.raises(Rejection):
        parts.budget.spend("c1", ["Zz one", "Zz two"], datetime.now(UTC))
    for path in ("/", "/p/people/1", f"/v/{_token(parts)}"):
        assert 'class="alarm"' in client.get(path, headers=cookie).text


def test_an_unreadable_database_is_a_fixed_500_not_no_rows(
    client: TestClient, parts: Parts, cookie: dict[str, str]
) -> None:
    token = _token(parts)
    con = sqlite3.connect(parts.db)
    con.execute("ALTER TABLE people RENAME TO zzgone")
    con.commit()
    con.close()
    response = client.get(f"/v/{token}", headers=cookie)
    assert (response.status_code, response.text) == (500, "internal error\n")
