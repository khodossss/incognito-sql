"""Append-only audit log: one JSON line per query, never a personal value.

Lines are chained (``incognito_sql.core.audit_chain``) when the log is opened with a
``Chain``: each carries its number ``n`` and the keyed digest ``prev`` of the line before.
"""

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlglot import exp

from incognito_sql.core.audit_chain import Chain, locked
from incognito_sql.core.errors import Reason
from incognito_sql.core.sql.policy import PolicyResult
from incognito_sql.core.tokens.store import TokenStore

_PRIVATE = 0o600


class AuditLog:
    """JSONL file opened for append, created private (0600) where the OS supports it."""

    def __init__(self, path: Path, chain: Chain | None = None) -> None:
        """Create the file if missing; owner-only permissions either way."""
        self._path = path
        self._chain = chain
        self._lock = threading.Lock()
        # Write access is checked now; nothing is written through this descriptor.
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, _PRIVATE))
        path.chmod(_PRIVATE)  # a file that existed keeps its mode otherwise

    def record(  # noqa: PLR0913
        self,
        *,
        outcome: str,
        reason: Reason | None,
        tables: list[str],
        row_count: int,
        ms: int,
        sql_tokenized: str | None,
        masked: list[str] | None = None,
        columns: list[str] | None = None,
        probes: int = 0,
    ) -> None:
        """Append one line. ``sql_tokenized`` is None when the query never passed the policy.

        ``masked`` names the columns whose cells were masked as looking personal, and
        the kind seen (``orders.note: email``), never a value. ``columns`` names the
        base columns the query names (``people.full_name``), refused or not; those
        behind a ``*`` once the query is prepared. ``probes`` is what the query spent
        of the probe budget.
        """
        entry: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "outcome": outcome,
            "reason": reason.value if reason else None,
            "tables": tables,
            "row_count": row_count,
            "ms": ms,
            "sql_tokenized": sql_tokenized,
            "masked": masked or [],
            "columns": columns or [],
            "probes": probes,
        }
        with self._lock:
            if self._chain is None:
                self._append(json.dumps(entry, ensure_ascii=False))
                return
            with locked(self._path):  # other processes append to the same log
                n, entry["prev"] = self._chain.next(self._path)
                entry["n"] = n
                line = json.dumps(entry, ensure_ascii=False)
                self._append(line)
                self._chain.wrote(n, line)

    def close(self) -> None:
        """Close the chain's anchor, if the log is chained."""
        if self._chain is not None:
            self._chain.close()

    def _append(self, line: str) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def tokenize_sql_for_audit(
    tree: exp.Expr, policy: PolicyResult, store: TokenStore | None, now: datetime, *, dialect: str
) -> str:
    """Return the query's SQL with each identifier-compared literal replaced by its token.

    A literal of a probe (`<`, `LIKE` ...) of an identifier is replaced by `?`, and so is
    every identifier-compared literal when `store` is None: a query refused before it
    spent its literals issues no token for them.

    The tree is not changed. Literals that are already tokens stay as they are. A
    literal's spelling is not remembered: the model wrote it, the database did not.
    """
    index = {id(node): i for i, node in enumerate(tree.walk())}
    chosen = {index[id(lit)] for lit in policy.pii_literals}
    probes = {index[id(lit)] for lit in policy.probe_literals}
    clone = tree.copy()
    for i, node in enumerate(list(clone.walk())):
        if i in chosen and store is not None:
            node.replace(exp.Literal.string(store.token_for(node.this, now)))
        elif i in chosen or i in probes:  # unspent, or a probe's: no value, no token
            node.replace(exp.Literal.string("?"))
    return clone.sql(dialect=dialect, comments=False)
