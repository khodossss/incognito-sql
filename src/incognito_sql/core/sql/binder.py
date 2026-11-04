"""Bind parameters of one query: names, values, and the type a compared value is cast to."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlglot import exp

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.bind_type import bind_cast, bind_domain
from incognito_sql.core.tokens.store import InvalidToken, TokenStore

# At most K forms per compared item, the earliest stored first.
MAX_FORMS = 16
# Bind parameters one statement may carry; SQLite builds before 3.32 stop at 999.
_PARAMS = {"tsql": 2100, "sqlite": 999}
_PARAMS_DEFAULT = 32767


@dataclass(frozen=True)
class PiiLiteral:
    """A literal compared to an identifier: a token or not, and the identifier's SQL type."""

    token: bool
    column_type: str


class Binder:
    """Collects bind values under the names p0, p1, ...; equal values share a name.

    Sharing keeps an expression and its GROUP BY copy identical for a server
    that binds parameters itself (PostgreSQL compares `$1` with `$1`, not with `$2`).
    """

    def __init__(self, store: TokenStore, now: datetime, dialect: str) -> None:
        """Bind for one query; `now` decides token expiry."""
        self.params: dict[str, object] = {}
        self._names: dict[tuple[type, str], str] = {}
        self._store = store
        self._now = now
        self._dialect = dialect

    @property
    def max_params(self) -> int:
        """Return how many bind parameters one statement of this dialect may carry."""
        return _PARAMS.get(self._dialect, _PARAMS_DEFAULT)

    def bind(self, value: object) -> exp.Placeholder:
        """Return the placeholder of a value, adding it on first sight."""
        key = (type(value), str(value))  # `1` and `1.0` and `'1'` stay apart
        name = self._names.get(key)
        if name is None:
            name = self._names[key] = f"p{len(self.params)}"
            if isinstance(value, Decimal) and self._dialect == "sqlite":
                value = float(value)  # sqlite3 cannot bind Decimal; SQLite reads 1.5 as REAL
            self.params[name] = value
        return exp.Placeholder(this=name)

    def bind_as(self, value: object, column_type: str) -> exp.Expr:
        """Return the placeholder of a value compared with a column, cast to its exact type.

        The DBMS then never converts the column's stored values to the bind's type.
        """
        placeholder = self.bind(value)
        target = bind_cast(column_type, self._dialect)
        return placeholder if target is None else exp.Cast(this=placeholder, to=target)

    def variants(self, lit: exp.Literal, pii: PiiLiteral) -> list[object]:
        """Return the values a compared literal or token stands for, checked against the column.

        Each raw form is kept only if it passes the strict check of the column's
        exact type. A literal that does not pass itself is refused
        (LITERAL_TYPE_MISMATCH); the stored forms behind a token or a literal are
        dropped silently, so an empty list may come back. At most MAX_FORMS values
        come back, the literal itself and then the earliest stored forms.
        """
        raws = self._token_forms(lit.this) if pii.token else None
        domain = bind_domain(pii.column_type, self._dialect)
        if raws is None:
            raws = self._store.variants_for_literal(lit.this)
            if domain.check(raws[0]) is None:  # the literal itself: the model's own text
                raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
        checked = (domain.check(raw) for raw in raws)
        return list(dict.fromkeys(v for v in checked if v is not None))[:MAX_FORMS]

    def _token_forms(self, token: str) -> list[str]:
        try:
            return self._store.variants(token, self._now)
        except InvalidToken:
            raise Rejection(Reason.INVALID_TOKEN) from None
