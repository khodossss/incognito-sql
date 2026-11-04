"""Suspicious open cells: a masker per answer, and a warning to the admin per column."""

import logging
from datetime import datetime

from incognito_sql.core.config import Declaration, verified_columns
from incognito_sql.core.output.mask import Masker
from incognito_sql.core.tokens.store import TokenStore

_LOG = logging.getLogger("incognito_sql.core.output")
COMPUTED = "a computed result column"
_ADVICE = (
    "%s holds values that look like personal data (%s); they reach the model masked. "
    "Run `incognito-sql init` and declare the column hidden, or list it under verified_open."
)


class Suspects:
    """Masks what looks personal in open cells and names the columns it came from."""

    def __init__(self, decl: Declaration, store: TokenStore) -> None:
        """Masks are tokens of the store's mask domain, never an identifier's."""
        self._decl = decl
        self._masks = store.masks()
        self._verified = verified_columns(decl)
        self._warned: set[str] = set()

    def masker(self, origins: tuple[str, ...], now: datetime) -> Masker:
        """Mask as links in web mode; skip output columns straight from verified columns."""
        checked = frozenset(i for i, o in enumerate(origins) if o in self._verified)
        if not self._decl.web_enabled:
            return Masker(checked=checked)
        port, masks = self._decl.web_port, self._masks
        return Masker(lambda v: f"http://127.0.0.1:{port}/m/{masks.tokenize(v, now)}", checked)

    def caught(self, masker: Masker, origins: tuple[str, ...], tables: list[str]) -> list[str]:
        """Name each masked column and the kind seen; warn the admin once per column.

        A column that is not a base column itself is named by the tables the query read.
        """
        computed = f"{COMPUTED} over {', '.join(tables)}"
        caught: list[str] = []
        for index, kind in sorted(masker.found.items()):
            column = origins[index] or computed  # one origin per output column
            caught.append(f"{column}: {kind}")
            if column not in self._warned:
                self._warned.add(column)
                _LOG.warning(_ADVICE, column, kind)
        return caught
