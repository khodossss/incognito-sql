"""Outer layer of every request: Host check, session check, safety headers, quiet errors."""

import logging

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from incognito_sql.web.session import Sessions, cookie_name

LOGIN_PREFIX = "/login/"
BAD_HOST = "bad host\n"
NO_SESSION = "sign in first: run `incognito-sql login`\n"
FAILED = "internal error\n"
SAFETY_HEADERS = [
    (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
]
_LOG = logging.getLogger("incognito_sql.web")


class Guard:
    """Wraps the card app.

    A Host other than ``127.0.0.1:<port>`` or ``localhost:<port>`` gets 400
    (DNS rebinding); then any path but ``/login/...`` without a live session
    gets 401. Every response carries the safety headers. A failure is logged as
    one fixed line with the exception type only, never the path or the query.
    """

    def __init__(self, app: ASGIApp, *, port: int, sessions: Sessions) -> None:
        """Wrap ``app`` for a web bound to ``port``."""
        self._app = app
        self._hosts = {f"127.0.0.1:{port}".encode(), f"localhost:{port}".encode()}
        self._sessions = sessions
        self._cookie = cookie_name(port)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check the request, then pass it on with the headers added to the response."""
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)
            return
        if scope["type"] != "http":
            return  # no websockets
        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = [*message.get("headers", []), *SAFETY_HEADERS]
            await send(message)

        try:  # the session check reads the store too: its errors stay quiet as well
            refusal = await self._refusal(scope)
            app: ASGIApp = self._app if refusal is None else refusal
            await app(scope, receive, guarded_send)
        except Exception as exc:  # noqa: BLE001 -- the traceback may quote values
            _LOG.warning("web request failed: %s", type(exc).__name__)
            if not started:
                await PlainTextResponse(FAILED, 500)(scope, receive, guarded_send)

    async def _refusal(self, scope: Scope) -> PlainTextResponse | None:
        hosts = [value for name, value in scope["headers"] if name == b"host"]
        if len(hosts) != 1 or hosts[0] not in self._hosts:
            return PlainTextResponse(BAD_HOST, 400)
        if scope["path"].startswith(LOGIN_PREFIX):
            return None
        cookie = Request(scope).cookies.get(self._cookie, "")
        if not cookie or not await run_in_threadpool(self._sessions.valid, cookie):
            return PlainTextResponse(NO_SESSION, 401)
        return None
