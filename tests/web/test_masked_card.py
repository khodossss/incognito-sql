"""`/m/<token>`: a masked open cell shown to the signed-in human, and only there."""

from starlette.testclient import TestClient

from .conftest import Parts

VALUE = "Write to <b>ivan@example.com</b>"


def test_a_mask_token_opens_its_value(
    client: TestClient, parts: Parts, cookie: dict[str, str]
) -> None:
    token = parts.store.masks().tokenize(VALUE, parts.clock())
    page = client.get(f"/m/{token}", headers=cookie)
    assert page.status_code == 200
    assert "Write to &lt;b&gt;ivan@example.com&lt;/b&gt;" in page.text
    assert "verified_open" in page.text


def test_mask_and_value_tokens_do_not_cross(
    client: TestClient, parts: Parts, cookie: dict[str, str]
) -> None:
    mask = parts.store.masks().tokenize(VALUE, parts.clock())
    ident = parts.store.tokenize(VALUE, parts.clock())
    assert client.get(f"/v/{mask}", headers=cookie).status_code == 404
    assert client.get(f"/m/{ident}", headers=cookie).status_code == 404
    assert client.get("/m/tk_aaaaaaaaaaaaaaaa", headers=cookie).status_code == 404


def test_a_mask_needs_a_session(client: TestClient, parts: Parts) -> None:
    token = parts.store.masks().tokenize(VALUE, parts.clock())
    page = client.get(f"/m/{token}")
    assert page.status_code == 401
    assert "ivan" not in page.text
