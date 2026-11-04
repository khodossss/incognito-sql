"""The session cookie is named per port: two configs on one host keep their own sessions."""

from pathlib import Path

from starlette.testclient import TestClient

from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.web.app import build_app
from incognito_sql.web.session import Sessions, cookie_name

from .conftest import DECL, PORT, Parts

OTHER_PORT = PORT + 1


def _sign_in(client: TestClient, sessions: Sessions) -> str:
    login = client.get(f"/login/{sessions.issue_code()}")
    return login.headers["set-cookie"].split(";", 1)[0]


def test_two_ports_keep_their_own_sessions(parts: Parts, tmp_path: Path) -> None:
    other = Sessions(tmp_path / "other.tokens.db", Cipher(bytes(range(32))))
    decl = DECL.model_copy(update={"web_port": OTHER_PORT})
    webs = [
        (build_app(DECL, parts.store, parts.engine, parts.sessions, parts.budget), PORT),
        (build_app(decl, parts.store, parts.engine, other, parts.budget), OTHER_PORT),
    ]
    clients = [
        TestClient(app, base_url=f"http://127.0.0.1:{port}", follow_redirects=False)
        for app, port in webs
    ]
    try:
        jar = [_sign_in(clients[0], parts.sessions), _sign_in(clients[1], other)]
        names = [pair.split("=", 1)[0] for pair in jar]
        assert names == [cookie_name(PORT), cookie_name(OTHER_PORT)]
        assert names == [f"incognito_session_{PORT}", f"incognito_session_{OTHER_PORT}"]
        both = {"cookie": "; ".join(jar)}  # cookies ignore the port: a browser sends both
        assert [c.get("/", headers=both).status_code for c in clients] == [200, 200]
        swapped = {"cookie": f"{names[0]}={jar[1].split('=', 1)[1]}"}
        assert clients[0].get("/", headers=swapped).status_code == 401
    finally:
        for c in clients:
            c.close()
        other.close()


def test_the_cookie_lives_as_long_as_the_configured_session(parts: Parts) -> None:
    decl = DECL.model_copy(update={"session_ttl_s": 3600})
    app = build_app(decl, parts.store, parts.engine, parts.sessions, parts.budget)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False) as client:
        login = client.get(f"/login/{parts.sessions.issue_code()}")
    assert "Max-Age=3600" in [a.strip() for a in login.headers["set-cookie"].split(";")]
