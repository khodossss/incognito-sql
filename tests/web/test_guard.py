"""Every request: Host check first, then the session; fixed bodies; safety headers."""

import logging
import sqlite3
from datetime import UTC, datetime

import pytest
from httpx2 import Response
from starlette.testclient import TestClient

from incognito_sql.web.guard import BAD_HOST, NO_SESSION

from .conftest import PORT, Parts

SAFETY = {
    "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


def _token(parts: Parts, value: str = "Ivan Petrov") -> str:
    return parts.store.tokenize(value, datetime.now(UTC))


def _assert_safe(response: Response) -> None:
    for name, value in SAFETY.items():
        assert response.headers[name] == value


def _all_text(response: Response) -> str:
    return response.text + repr(response.headers.multi_items())


def test_no_session_is_401_without_the_value(client: TestClient, parts: Parts) -> None:
    token = _token(parts)
    response = client.get(f"/v/{token}")
    assert (response.status_code, response.text) == (401, NO_SESSION)
    _assert_safe(response)
    text = _all_text(response)
    assert "Ivan" not in text
    assert token not in text


@pytest.mark.parametrize("host", ["evil.test", f"evil.test:{PORT}", "127.0.0.1:1", "127.0.0.1"])
def test_foreign_host_is_400_before_the_session(
    client: TestClient, parts: Parts, cookie: dict[str, str], host: str
) -> None:
    token = _token(parts)
    for headers in ({"host": host}, {"host": host, **cookie}):
        response = client.get(f"/v/{token}", headers=headers)
        assert (response.status_code, response.text) == (400, BAD_HOST)
        _assert_safe(response)
        assert "Ivan" not in _all_text(response)
        assert token not in _all_text(response)


@pytest.mark.parametrize("host", [f"127.0.0.1:{PORT}", f"localhost:{PORT}"])
def test_local_hosts_pass(client: TestClient, cookie: dict[str, str], host: str) -> None:
    response = client.get("/", headers={"host": host, **cookie})
    assert response.status_code == 200
    _assert_safe(response)


def test_login_sets_a_lax_cookie_and_leaves_the_address(client: TestClient, parts: Parts) -> None:
    code = parts.sessions.issue_code()
    response = client.get(f"/login/{code}")
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    _assert_safe(response)
    [set_cookie] = response.headers.get_list("set-cookie")
    attributes = [a.strip() for a in set_cookie.split(";")]
    assert {"HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=28800"} <= set(attributes)
    assert attributes[0].startswith(f"incognito_session_{PORT}=")
    assert "secure" not in set_cookie.casefold()
    assert code not in set_cookie
    name_value = attributes[0]
    assert client.get("/", headers={"cookie": name_value}).status_code == 200


def test_a_code_works_once(client: TestClient, parts: Parts) -> None:
    code = parts.sessions.issue_code()
    assert client.get(f"/login/{code}").status_code == 303
    again = client.get(f"/login/{code}")
    assert again.status_code == 401
    assert "set-cookie" not in again.headers
    assert code not in _all_text(again)


def test_unknown_paths_need_a_session_too(client: TestClient, cookie: dict[str, str]) -> None:
    assert client.get("/zz-nowhere").status_code == 401
    missing = client.get("/zz-nowhere", headers=cookie)
    assert missing.status_code == 404
    _assert_safe(missing)


def test_a_server_error_is_one_fixed_warning(
    client: TestClient, parts: Parts, cookie: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    con = sqlite3.connect(parts.db)
    con.execute("ALTER TABLE people RENAME TO zzgone")
    con.commit()
    con.close()
    with caplog.at_level(logging.DEBUG):
        response = client.get("/p/people/1", headers=cookie)
    assert response.status_code == 500
    _assert_safe(response)
    assert "people" not in response.text
    loud = [(r.levelno, r.getMessage()) for r in caplog.records if r.levelno >= logging.WARNING]
    assert loud == [(logging.WARNING, "web request failed: OperationalError")]


def test_a_failing_session_check_is_one_fixed_warning(
    client: TestClient,
    parts: Parts,
    cookie: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def locked(_cookie: str) -> bool:
        msg = "Zz database is locked"
        raise sqlite3.OperationalError(msg)

    monkeypatch.setattr(parts.sessions, "valid", locked)
    with caplog.at_level(logging.DEBUG):
        response = client.get("/p/people/1", headers=cookie)
    assert (response.status_code, response.text) == (500, "internal error\n")
    _assert_safe(response)
    loud = [(r.levelno, r.getMessage()) for r in caplog.records if r.levelno >= logging.WARNING]
    assert loud == [(logging.WARNING, "web request failed: OperationalError")]
