"""The server's checks on one query, up to execution: the verdict and what it reads."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from incognito_sql.core.config import ColumnClass, Declaration, column_class
from incognito_sql.core.errors import Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import PolicyResult, enforce
from incognito_sql.core.sql.resolve import qualify_tree
from incognito_sql.core.sql.rewrite import Prepared, prepare
from incognito_sql.core.tokens.crypto import KEY_LEN, Cipher
from incognito_sql.core.tokens.store import TokenStore

PSEUDONYM, VALUE = "pseudonym", "value"
MEMORY = Path(":memory:")  # SQLite's in-memory database: no file is ever made


@dataclass(frozen=True)
class Verdict:
    """What the server would answer: a refusal code or the shape of the answer.

    ``reads``: (table, column, class) of every base column the query reads, as far as
    the checks got. ``outputs``: per output column of the rewritten query (a ``*``
    expanded), ``pseudonym`` or ``value``; empty for a refusal. ``tokens``: the query
    holds tokens, so an answer holds only if they are live.
    """

    error: str | None
    reads: tuple[tuple[str, str, str], ...]
    outputs: tuple[str, ...] = ()
    tokens: bool = False


def verdict(sql: str, decl: Declaration, catalog: Catalog) -> Verdict:
    """Run the server's checks up to execution: nothing is executed or kept.

    Parsing, the allowlist, name resolution, the policy, and the rewrite with the check
    of the SQL it writes, on a token store in memory where every token is live and
    stands for no value. The literal budget is not spent: it needs the server's session.
    """
    qualified: exp.Expr | None = None
    try:
        tree = parse(sql, decl.dialect, decl.limits)
        check_nodes(tree)
        qualified = qualify_tree(tree, catalog, decl.dialect)
        policy = enforce(qualified, catalog, decl)
        prepared = _rewrite(qualified, policy, catalog, decl)
    except Rejection as exc:
        reads = _reads(qualified, catalog, decl) if qualified is not None else ()
        return Verdict(exc.reason.value, reads)
    outputs = tuple(
        PSEUDONYM if cls is ColumnClass.IDENTIFIER else VALUE for cls in prepared.output_classes
    )
    return Verdict(None, _reads(qualified, catalog, decl), outputs, tokens=bool(policy.pii_tokens))


class _ProbeStore(TokenStore):
    """A store in memory where every token is live and stands for no stored value.

    The rewrite then goes on past each token as for a live one, to the check of the SQL
    it writes; whether a token is really live only the server's own store can tell.
    """

    def variants(self, token: str, now: datetime) -> list[str]:  # noqa: ARG002
        """Return no raw form: a live token whose forms the rewrite cannot see."""
        return []


def _rewrite(tree: exp.Expr, policy: PolicyResult, catalog: Catalog, decl: Declaration) -> Prepared:
    """Rewrite and recheck as the server does, on a store held in memory only.

    A literal of the query may be a real name: nothing of it reaches a file, and the
    store is gone when the probe ends, however it ends.
    """
    store = _ProbeStore(MEMORY, Cipher(os.urandom(KEY_LEN)), "try", None)
    try:
        return prepare(tree, policy, store, catalog, decl, datetime.now(UTC))
    finally:
        store.close()


def _reads(tree: exp.Expr, catalog: Catalog, decl: Declaration) -> tuple[tuple[str, str, str], ...]:
    """Return (table, column, class) of each base column read, in name order."""
    found: set[tuple[str, str, str]] = set()
    for scope in traverse_scope(tree):
        for column in scope.columns:
            source = scope.sources.get(column.table)
            if not isinstance(source, exp.Table):
                continue  # a derived table or CTE: its own scope reads the base
            table = catalog.table(source.name)
            if table is None or column.name not in catalog.columns[table]:
                continue
            cls = column_class(decl, table, column.name)
            found.add((table, column.name, str(cls) if cls is not None else "hidden"))
    return tuple(sorted(found))
