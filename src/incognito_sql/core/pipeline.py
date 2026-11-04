"""One query from SQL text to the model-facing answer, audited."""

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlglot import exp

from incognito_sql.core.audit import AuditLog, tokenize_sql_for_audit
from incognito_sql.core.budget import LiteralBudget, Spend
from incognito_sql.core.config import Declaration
from incognito_sql.core.describe import describe
from incognito_sql.core.display import DisplayIds, remember_forms
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.exec.run import execute
from incognito_sql.core.output.shape import shape
from incognito_sql.core.output.suspects import Suspects
from incognito_sql.core.rate import QueryRate
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.catalog import reflect
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.origin import read_columns
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import enforce
from incognito_sql.core.sql.resolve import qualify_tree
from incognito_sql.core.sql.rewrite import prepare
from incognito_sql.core.sql.row_mask import unruled_readers
from incognito_sql.core.tokens.store import TokenStore

_LOG = logging.getLogger("incognito_sql.core.pipeline")


@dataclass
class _Trace:
    """What the audit line learns while a query moves through the stages."""

    tables: list[str] = field(default_factory=list)
    sql_tokenized: str | None = None
    row_count: int = 0
    masked: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    spend: Spend = field(default_factory=Spend)


class Gateway:
    """Runs model-written SQL against the database without returning identifier values."""

    def __init__(  # noqa: PLR0913
        self,
        decl: Declaration,
        store: TokenStore,
        engine: Engine,
        audit: AuditLog,
        budget: LiteralBudget,
        *,
        rate: QueryRate | None = None,
    ) -> None:
        """Reflect the database once; the catalog is fixed for the gateway's life."""
        self._decl = decl
        self._store = store
        self._engine = engine
        self._audit = audit
        self._budget = budget
        self._rate = rate
        self._catalog = reflect(engine, decl.dialect)
        self._rng = random.SystemRandom()
        self._display_ids = DisplayIds(decl, self._catalog, store, engine)
        self._suspects = Suspects(decl, store)

    def describe(self) -> dict[str, object]:
        """Return the tables, their usable columns with classes, and hidden-column counts."""
        return describe(self._decl, self._catalog)

    def unruled_readers(self) -> list[str]:
        """Return the open relations that may show ruled rows unmasked; the start stops on them."""
        return unruled_readers(self._decl, self._catalog)

    def query(self, sql: str, connection_id: str, now: datetime | None = None) -> dict[str, object]:
        """Answer one query; a refusal is `{"error": reason, "sqlstate": ...}`.

        Every call, answered or not, writes one audit line. An unexpected failure
        answers `{"error": "internal_error"}` and logs only the exception type.
        """
        return self.ask(sql, connection_id, now)[0]

    def ask(
        self, sql: str, connection_id: str, now: datetime | None = None
    ) -> tuple[dict[str, object], Spend]:
        """Answer one query as ``query`` does, with what it spent of the budgets.

        A query refused before the budgets spent nothing; one refused past them, by
        the database or a limit, has spent.
        """
        now = now or datetime.now(UTC)
        start = time.monotonic()
        trace = _Trace()
        reason: Reason | None = None
        try:
            if self._rate is not None:  # first, before parsing: a refused query counts too
                self._rate.hit(now)
            answer = self._answer(sql, connection_id, now, trace)
            outcome = "ok"
        except Rejection as exc:
            outcome, reason = "rejected", exc.reason
            answer = {"error": exc.reason.value, "sqlstate": exc.sqlstate}
            if exc.detail is not None:
                answer["detail"] = exc.detail
        except Exception as exc:  # noqa: BLE001 -- a bug must not reach the model
            _LOG.warning("query failed: %s", type(exc).__name__)
            outcome, reason = "error", Reason.INTERNAL_ERROR
            answer = {"error": Reason.INTERNAL_ERROR.value}
        try:
            self._audit.record(
                outcome=outcome,
                reason=reason,
                tables=trace.tables,
                row_count=trace.row_count,
                ms=int((time.monotonic() - start) * 1000),
                sql_tokenized=trace.sql_tokenized,
                masked=trace.masked,
                columns=trace.columns,
                probes=trace.spend.probes,
            )
        except Exception as exc:  # noqa: BLE001 -- an unaudited answer is not given
            _LOG.warning("audit failed: %s", type(exc).__name__)
            return {"error": Reason.INTERNAL_ERROR.value}, trace.spend
        return answer, trace.spend

    def close(self) -> None:
        """Close the token store, the budget, the audit log's anchor and the engine."""
        self._store.close()
        self._budget.close()
        self._audit.close()
        if self._rate is not None:
            self._rate.close()
        self._engine.dispose()

    def _answer(
        self, sql: str, connection_id: str, now: datetime, trace: _Trace
    ) -> dict[str, object]:
        decl = self._decl
        tree = parse(sql, decl.dialect, decl.limits)
        check_nodes(tree)
        qualified = qualify_tree(tree, self._catalog, decl.dialect)
        trace.tables = sorted(
            {t.name for t in qualified.find_all(exp.Table)} & set(self._catalog.columns)
        )
        trace.columns = read_columns(qualified, Lineage(qualified, self._catalog, decl))
        policy = enforce(qualified, self._catalog, decl)
        trace.sql_tokenized = tokenize_sql_for_audit(
            qualified, policy, None, now, dialect=decl.dialect
        )
        prepared = prepare(qualified, policy, self._store, self._catalog, decl, now)
        trace.columns = sorted(set(trace.columns) | {o for o in prepared.origins if o})
        # The budgets right before the database: a query refused earlier (a limit, a
        # stored form that cannot be bound) tells nothing of the data and spends nothing;
        # one refused by the database or past it has spent. The token store after the
        # budget: a literal over it leaves nothing there.
        trace.spend = self._budget.spend(
            connection_id,
            [str(lit.this) for lit in policy.pii_literals],
            now,
            exact=[str(lit.this) for lit in policy.probe_literals],
            probes=policy.probes,
        )
        trace.sql_tokenized = tokenize_sql_for_audit(
            qualified, policy, self._store, now, dialect=decl.dialect
        )
        rows = execute(self._engine, prepared, decl.limits)
        trace.row_count = len(rows.rows)
        if not decl.web_enabled:
            remember_forms(rows, prepared.output_classes, self._store, now)
        masker = self._suspects.masker(prepared.origins, now)
        answer = shape(
            rows,
            prepared.output_classes,
            self._store,
            decl,
            now,
            self._rng,
            hidden_count=prepared.hidden_count,
            display_ids=self._display_ids,
            keep_order=prepared.ordered,
            masker=masker,
        )
        trace.masked = self._suspects.caught(masker, prepared.origins, trace.tables)
        return answer
