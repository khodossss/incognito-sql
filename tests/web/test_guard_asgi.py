"""The guard around any ASGI app: the request passes through whole, the headers are added."""

from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from incognito_sql.web.guard import SAFETY_HEADERS, Guard

from .conftest import BASE, PORT, Parts


async def _echo(scope: Scope, receive: Receive, send: Send) -> None:
    """Answer with the request body and no headers of its own (ASGI allows that)."""
    del scope
    body = b""
    more = True
    while more:
        message = await receive()
        body += message.get("body", b"")
        more = message.get("more_body", False)
    await send({"type": "http.response.start", "status": 200})
    await send({"type": "http.response.body", "body": body})


def test_the_body_reaches_the_app_and_the_answer_is_guarded(
    parts: Parts, cookie: dict[str, str]
) -> None:
    guarded = Guard(_echo, port=PORT, sessions=parts.sessions)
    client = TestClient(guarded, base_url=BASE)  # no lifespan: the echo app has none
    response = client.post("/echo", content=b"zz-request-body", headers=cookie)
    assert (response.status_code, response.content) == (200, b"zz-request-body")
    for name, value in SAFETY_HEADERS:
        assert response.headers[name.decode()] == value.decode()
