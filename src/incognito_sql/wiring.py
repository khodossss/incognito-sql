"""Opening the parts that live next to a config: gateway, token store, card web."""

from contextlib import ExitStack
from pathlib import Path

from sqlalchemy.engine import URL, make_url

from incognito_sql.core.audit import AuditLog
from incognito_sql.core.audit_chain import Anchor, Chain
from incognito_sql.core.budget import LiteralBudget
from incognito_sql.core.config import Declaration
from incognito_sql.core.db import make_engine
from incognito_sql.core.pipeline import Gateway
from incognito_sql.core.rate import QueryRate
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore
from incognito_sql.web.run import WebParts, open_web


def token_domain(cipher: Cipher, dsn: str) -> str:
    """Name the database for the token store: keyed digest of the DSN without its password.

    A password rotation keeps the domain, so issued tokens stay valid.
    """
    url = make_url(dsn)
    bare = URL.create(
        url.drivername, url.username, None, url.host, url.port, url.database, url.query
    )
    return "db:" + cipher.mac(bare.render_as_string(hide_password=False)).hex()[:16]


def store_path(config: Path) -> Path:
    """Return the token store file next to the config: ``<config stem>.tokens.db``."""
    return config.parent / f"{config.stem}.tokens.db"


def audit_path(config: Path) -> Path:
    """Return the audit log next to the config: ``<config stem>.audit.jsonl``."""
    return config.parent / f"{config.stem}.audit.jsonl"


def open_gateway(config: Path, decl: Declaration, dsn: str, key: bytes) -> Gateway:
    """Open the database, the token store, budget and audit log next to the config.

    Whatever was opened is closed again if a later step fails.
    """
    cipher = Cipher(key)
    tokens = store_path(config)
    with ExitStack() as opened:
        engine = make_engine(
            dsn, decl.dialect, statement_timeout_ms=decl.limits.statement_timeout_ms
        )
        opened.callback(engine.dispose)
        store = TokenStore(tokens, cipher, token_domain(cipher, dsn), decl.token_ttl_s)
        opened.callback(store.close)
        budget = LiteralBudget(tokens, cipher, decl.limits)
        opened.callback(budget.close)
        anchor = Anchor(tokens)
        opened.callback(anchor.close)
        audit = AuditLog(audit_path(config), Chain(cipher, anchor))
        rate = QueryRate(tokens, decl.limits)
        opened.callback(rate.close)
        gateway = Gateway(decl, store, engine, audit, budget, rate=rate)
        opened.pop_all()
    return gateway


def open_cards(config: Path, decl: Declaration, dsn: str, key: bytes) -> WebParts:
    """Open the card web on the gateway's token store, with its own read-only engine."""
    cipher = Cipher(key)
    return open_web(decl, dsn, store_path(config), token_domain(cipher, dsn), cipher)
