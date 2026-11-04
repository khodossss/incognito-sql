"""Plausible queries: each column used the way its class allows, so the gateway answers many."""

import random

from bench.fuzz.vocab import (
    AGGREGATES,
    P_AGGREGATE,
    P_GROUP_KEY,
    P_ORDER,
    P_PLAIN,
    P_VISIBLE,
    VISIBLE,
    Source,
)


class Plausible:
    """Select items and predicates that use an identifier only as is, counted or by token."""

    _rng: random.Random
    _dialect: str

    def _maybe(self, chance: float) -> bool:
        return self._rng.random() < chance

    def _pick(self, sources: list[Source]) -> tuple[str, str | None]:
        """Return a column reference and its class; mostly a visible column."""
        source = self._rng.choice(sources)
        visible = [c for c in source.columns if c.cls in VISIBLE] or list(source.columns)
        pool = visible if self._maybe(P_VISIBLE) else list(source.columns)
        column = self._rng.choice(pool)
        return f"{source.alias}.{column.quoted(self._dialect)}", column.cls

    def _plausible_items(self, sources: list[Source], width: int) -> tuple[list[str], str, str]:
        """Return select items, GROUP BY and ORDER BY: all aggregates, or all plain columns."""
        if self._maybe(P_AGGREGATE):
            exprs, group = [], ""
            if self._maybe(P_GROUP_KEY):
                key, _ = self._pick(sources)
                exprs, group = [key], f" GROUP BY {key}"
            exprs += [self._aggregate(sources) for _ in range(max(width - len(exprs), 1))]
            return exprs, group, ""
        exprs = [self._plain(sources) for _ in range(width)]
        ref, cls = self._pick(sources)
        order = f" ORDER BY {ref}" if cls != "identifier" and self._maybe(P_ORDER) else ""
        return exprs, "", order

    def _plain(self, sources: list[Source]) -> str:
        ref, cls = self._pick(sources)
        return ref if cls == "identifier" or self._maybe(P_PLAIN) else f"({ref} + 1)"

    def _aggregate(self, sources: list[Source]) -> str:
        ref, cls = self._pick(sources)
        if cls == "identifier":
            return f"COUNT(DISTINCT {ref})"
        return self._rng.choice((*AGGREGATES, "COUNT(*)")).format(ref)

    def _plausible_predicate(self, sources: list[Source]) -> str:
        ref, cls = self._pick(sources)
        if cls == "identifier":
            token = "'{{TOKEN_OWN}}'"  # noqa: S105 -- a template, not a secret
            return self._rng.choice((f"{ref} = {token}", f"{ref} IN ('x', {token})"))
        return self._rng.choice((f"{ref} > 1", f"{ref} BETWEEN 1 AND 100", f"{ref} IS NULL"))
