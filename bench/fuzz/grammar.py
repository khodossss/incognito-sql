"""Random SQL over the bench world: every column class, functions, casts, subqueries, sets.

The same seed gives the same queries. Half are wild (any expression over any column);
half are plausible (``bench.fuzz.plausible``), so that accepted queries, whose answers
could leak, are common enough to matter.
"""

import random
from typing import TYPE_CHECKING

from bench.fuzz.plausible import Plausible
from bench.fuzz.vocab import (
    AGGREGATES,
    CASTS,
    DEFAULT_CASTS,
    EXPR_DEPTH,
    FUNCS,
    JOINS,
    LITERALS,
    MAX_LIMIT,
    MAX_WIDTH,
    P_COMPOUND,
    P_DISTINCT,
    P_GROUP,
    P_JOIN,
    P_LEAF_COLUMN,
    P_LIMIT,
    P_ORDER,
    P_PLAUSIBLE,
    P_TOP,
    P_UNION,
    P_WHERE,
    P_WITH,
    TABLES,
    Source,
)
from bench.schema import Column

if TYPE_CHECKING:
    from collections.abc import Callable


class Grammar(Plausible):
    """Draws one random query at a time for one DBMS."""

    def __init__(self, rng: random.Random, dialect: str) -> None:
        """Use ``rng`` for every choice; ``dialect`` picks spelling and existing columns."""
        self._rng = rng
        self._dialect = dialect
        self._plausible = False

    def query(self) -> str:
        """Return one random query: a SELECT, a UNION of two, or a WITH over one."""
        self._plausible = self._maybe(P_PLAUSIBLE)
        roll = self._rng.random()
        if roll < P_UNION:
            return f"{self._select(1, part=True)} UNION {self._select(1, part=True)}"
        if roll < P_UNION + P_WITH:
            return f"WITH t AS ({self._select(1, alias='v', part=True)}) SELECT v FROM t"
        return self._select(self._rng.randint(1, MAX_WIDTH))

    def _present(self, table: str) -> tuple[Column, ...]:
        return tuple(c for c in TABLES[table] if c.type_on(self._dialect))

    def _sources(self) -> list[Source]:
        table = self._rng.choice(list(TABLES))
        main = Source("a", table, self._present(table))
        if table == "users" and self._maybe(P_JOIN):
            other = self._rng.choice(list(JOINS))
            return [main, Source("b", other, self._present(other))]
        return [main]

    def _select(self, width: int, alias: str | None = None, *, part: bool = False) -> str:
        """Return one SELECT; a ``part`` of a UNION or WITH gets no ORDER BY or LIMIT."""
        sources = self._sources()
        head = "DISTINCT " if self._maybe(P_DISTINCT) else ""
        top = self._dialect == "tsql" and self._maybe(P_TOP)
        head += "TOP 5 " if top else ""
        if self._plausible:
            exprs, group, order = self._plausible_items(sources, width)
        else:
            exprs = [self._expr(sources, EXPR_DEPTH) for _ in range(width)]
            group = f" GROUP BY {self._column(sources)}" if self._maybe(P_GROUP) else ""
            order = f" ORDER BY {self._expr(sources, 1)}" if self._maybe(P_ORDER) else ""
        items = [f"{e} AS {alias or f'c{i}'}" for i, e in enumerate(exprs)]
        sql = f"SELECT {head}{', '.join(items)} FROM {sources[0].table} a"
        if len(sources) > 1:
            sql += f" JOIN {sources[1].table} b ON b.{JOINS[sources[1].table]} = a.id"
        if self._maybe(P_WHERE):
            sql += f" WHERE {self._predicate(sources, EXPR_DEPTH)}"
        sql += group
        if not part:
            sql += order
            if not top and self._dialect != "tsql" and self._maybe(P_LIMIT):
                sql += f" LIMIT {self._rng.randint(1, MAX_LIMIT)}"
        return sql

    def _column(self, sources: list[Source]) -> str:
        source = self._rng.choice(sources)
        return f"{source.alias}.{self._rng.choice(source.columns).quoted(self._dialect)}"

    def _literal(self) -> str:
        return self._rng.choice(LITERALS)

    def _expr(self, sources: list[Source], depth: int) -> str:
        if depth <= 0:
            return self._column(sources) if self._maybe(P_LEAF_COLUMN) else self._literal()

        def inner() -> str:
            return self._expr(sources, depth - 1)

        def case() -> str:
            return f"CASE WHEN {self._predicate(sources, depth - 1)} THEN {inner()} ELSE 0 END"

        casts = CASTS.get(self._dialect, DEFAULT_CASTS)
        builders: tuple[tuple[int, Callable[[], str]], ...] = (
            (35, lambda: self._column(sources)),
            (15, lambda: self._rng.choice(FUNCS).format(inner())),
            (12, lambda: self._rng.choice(AGGREGATES).format(inner())),
            (10, lambda: f"CAST({inner()} AS {self._rng.choice(casts)})"),
            (8, case),
            (8, lambda: f"({inner()} {self._rng.choice('+-*')} {inner()})"),
            (6, lambda: f"({self._scalar(depth - 1)})"),
            (6, self._literal),
        )
        makers = [make for _, make in builders]
        [make] = self._rng.choices(makers, [weight for weight, _ in builders])
        return make()

    def _scalar(self, depth: int) -> str:
        table = self._rng.choice(list(TABLES))
        source = Source("a", table, self._present(table))
        return f"SELECT MAX({self._expr([source], depth)}) FROM {table} a"

    def _predicate(self, sources: list[Source], depth: int) -> str:
        if self._plausible:
            return self._plausible_predicate(sources)
        left = self._expr(sources, max(depth - 1, 0))
        forms = (
            f"{left} = {self._literal()}",
            f"{left} = {self._column(sources)}",
            f"{left} <> {self._literal()}",
            f"{left} < {self._literal()}",
            f"{left} LIKE 'Z%'",
            f"{left} IN ({self._literal()}, {self._literal()})",
            f"{left} IS NULL",
            f"{left} BETWEEN 1 AND 100",
            f"EXISTS (SELECT 1 FROM users u WHERE u.id = {self._column(sources)})",
        )
        predicate = self._rng.choice(forms)
        if depth > 0 and self._maybe(P_COMPOUND):
            joiner = self._rng.choice((" AND ", " OR "))
            return f"({predicate}{joiner}{self._predicate(sources, depth - 1)})"
        return predicate
