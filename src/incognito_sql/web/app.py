"""The local card web: login, value cards and person cards."""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from incognito_sql.core.budget import LiteralBudget
from incognito_sql.core.config import Declaration
from incognito_sql.core.sql.catalog import reflect
from incognito_sql.core.tokens.store import TokenStore
from incognito_sql.web.cards import Cards, Row
from incognito_sql.web.guard import NO_SESSION, Guard
from incognito_sql.web.pages import index_page, masked_page, person_page, value_page
from incognito_sql.web.session import LoginRefused, Sessions, cookie_name

NOT_FOUND = "not found\n"
# Built by hand so the attributes are exactly these; no Secure: plain http on localhost.
# Lax, not Strict: a link clicked in a web chat is a cross-site navigation.
_COOKIE_ATTRS = "HttpOnly; SameSite=Lax; Path=/"


def _card[T](
    find: Callable[[Request], T | None], page: Callable[[T], str]
) -> Callable[[Request], Response]:
    """Serve the page of what ``find`` finds, or 404."""

    def handle(request: Request) -> Response:
        found = find(request)
        return PlainTextResponse(NOT_FOUND, 404) if found is None else HTMLResponse(page(found))

    return handle


def build_app(
    decl: Declaration,
    store: TokenStore,
    engine: Engine,
    sessions: Sessions,
    budget: LiteralBudget,
) -> Starlette:
    """Create the card web for ``127.0.0.1:<decl.web_port>``.

    ``GET /login/{code}`` spends a one-time code, sets the session cookie and
    redirects to ``/``; ``GET /v/{token}`` shows a value and the entity rows
    holding it; ``GET /m/{token}`` shows a masked open cell; ``GET /p/{entity}/{pk}``
    shows one entity row without secret or undeclared columns. Every other request needs a session.
    """
    cards = Cards(decl, store, engine, reflect(engine, decl.dialect))

    def alarm() -> bool:
        return budget.alarm_active(datetime.now(UTC))

    def login(request: Request) -> Response:
        try:
            cookie = sessions.exchange(request.path_params["code"])
        except LoginRefused:
            return PlainTextResponse(NO_SESSION, 401)
        response = RedirectResponse("/", status_code=303)
        response.headers.append(
            "set-cookie",
            f"{cookie_name(decl.web_port)}={cookie}; {_COOKIE_ATTRS}; Max-Age={decl.session_ttl_s}",
        )
        return response

    def index(_request: Request) -> Response:
        return HTMLResponse(index_page(alarm=alarm()))

    def value(request: Request) -> tuple[str, list[Row]] | None:
        return cards.value(request.path_params["token"])

    def masked(request: Request) -> str | None:
        return cards.masked(request.path_params["token"])

    def person(request: Request) -> Row | None:
        return cards.row(request.path_params["entity"], request.path_params["pk"])

    routes = [
        Route("/", index),
        Route("/login/{code}", login),
        Route("/v/{token}", _card(value, lambda f: value_page(*f, alarm=alarm()))),
        Route("/m/{token}", _card(masked, lambda f: masked_page(f, alarm=alarm()))),
        Route("/p/{entity}/{pk}", _card(person, lambda f: person_page(f, alarm=alarm()))),
    ]
    guard = Middleware(Guard, port=decl.web_port, sessions=sessions)
    return Starlette(routes=routes, middleware=[guard])
