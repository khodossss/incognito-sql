"""Every change between two declarations that bears on what the model may see or link.

WIDENED: the model may learn or link more. NARROWED: less. CHANGED: a difference that
opens nothing to the model (another database, a class change within one visibility).
"""

from incognito_sql.core.config import ColumnClass, Declaration, column_operations
from incognito_sql.core.config import verified_columns as verified
from incognito_sql.core.config.forms import forms
from incognito_sql.core.config.protection import OPENS
from incognito_sql.diff.kinds import CHANGED, NARROWED, WIDENED, Change
from incognito_sql.diff.rules import rule_changes

UNLIMITED = "unlimited"  # a budget with no limit
_HIDDEN = "hidden"  # a column the declaration does not list
# What the model sees of a column: nothing, a token, the value; an open entity key also
# names the rows of a person (`person_key`, the keys in labels).
_SEEN = {_HIDDEN: 0, "secret": 0, "free_text": 0, "identifier": 1, "quasi": 2, "open": 2}
_KEY = 3


def changes(old: Declaration, new: Declaration) -> list[Change]:
    """Return every change from ``old`` to ``new``, widenings first."""
    found = [*_classes(old, new), *_verified(old, new), *_relations(old, new)]
    found += _operations(old, new) + _forms(old, new) + _settings(old, new)
    found += rule_changes(old, new)
    order = {WIDENED: 0, NARROWED: 1, CHANGED: 2}
    return sorted(found, key=lambda c: (order[c.kind], c.where, c.what))


def _step(before: float, after: float) -> str:
    return WIDENED if after > before else NARROWED if after < before else CHANGED


def _cls(decl: Declaration, table: str, column: str) -> str:
    kind = decl.columns.get(table, {}).get(column)
    return _HIDDEN if kind is None else ColumnClass(kind).value


def _seen(decl: Declaration, table: str, column: str) -> int:
    cls = _cls(decl, table, column)
    keys = {(e.table.lower(), e.pk.lower()) for e in decl.entities}
    return _KEY if cls == "open" and (table, column) in keys else _SEEN[cls]


def _columns(old: Declaration, new: Declaration) -> list[tuple[str, str]]:
    pairs = {(t, c) for d in (old, new) for t, cols in d.columns.items() for c in cols}
    pairs |= {(e.table.lower(), e.pk.lower()) for d in (old, new) for e in d.entities}
    return sorted(pairs)


def _classes(old: Declaration, new: Declaration) -> list[Change]:
    found = []
    for t, c in _columns(old, new):
        before, after = _seen(old, t, c), _seen(new, t, c)
        names = (_cls(old, t, c), _cls(new, t, c))
        if before != after or names[0] != names[1]:
            what = f"{names[0]} -> {names[1]}"
            if _KEY in (before, after):
                what += " (an open entity key names a person's rows)"
            found.append(Change(_step(before, after), f"{t}.{c}", what))
    return found


def _verified(old: Declaration, new: Declaration) -> list[Change]:
    before, after = verified(old), verified(new)
    lifted = [Change(WIDENED, c, "verified_open: its mask is lifted") for c in after - before]
    return lifted + [Change(NARROWED, c, "verified_open removed") for c in before - after]


def _relations(old: Declaration, new: Declaration) -> list[Change]:
    before, after = set(old.verified_relations), set(new.verified_relations)
    opened = [
        Change(WIDENED, name, "verified_relations: read with no rule on rows")
        for name in sorted(after - before)
    ]
    closed = [Change(NARROWED, n, "verified_relations removed") for n in sorted(before - after)]
    return opened + closed


def _operations(old: Declaration, new: Declaration) -> list[Change]:
    found = []
    for t, c in _columns(old, new):
        if _cls(old, t, c) != "identifier" or _cls(new, t, c) != "identifier":
            continue  # a class change is reported on its own
        before, after = column_operations(old, t, c), column_operations(new, t, c)
        added, removed = after - before, before - after
        opening = sorted(op for op in added if op in OPENS)
        if opening:
            found.append(Change(WIDENED, f"{t}.{c}", f"operations added: {', '.join(opening)}"))
        if quiet := sorted(op for op in added if op not in OPENS):  # nothing new to learn
            found.append(Change(CHANGED, f"{t}.{c}", f"operations added: {', '.join(quiet)}"))
        if removed:
            names = ", ".join(sorted(removed))
            found.append(Change(NARROWED, f"{t}.{c}", f"operations removed: {names}"))
    return found


def _forms(old: Declaration, new: Declaration) -> list[Change]:
    before = forms(old.protection, old.protections)
    after = forms(new.protection, new.protections)
    found = []
    if added := sorted(after - before):
        found.append(Change(WIDENED, "protection", f"query forms added: {', '.join(added)}"))
    if removed := sorted(before - after):
        found.append(Change(NARROWED, "protection", f"query forms removed: {', '.join(removed)}"))
    return found


def _settings(old: Declaration, new: Declaration) -> list[Change]:
    no_expiry = float("inf")
    found = [
        _budget("limits.literal_budget", old.limits.literal_budget, new.limits.literal_budget),
        _budget("limits.probe_budget", old.limits.probe_budget, new.limits.probe_budget),
        # More queries in a window, or a shorter window: more answers to compare.
        _compare("limits.query_rate", old.limits.query_rate, new.limits.query_rate),
        _compare(
            "limits.query_window_s",
            -old.limits.query_window_s,
            -new.limits.query_window_s,
            shown=(old.limits.query_window_s, new.limits.query_window_s),
        ),
        # A shorter window gives the installation's budget back sooner.
        _compare(
            "limits.literal_window_s",
            -old.limits.literal_window_s,
            -new.limits.literal_window_s,
            shown=(old.limits.literal_window_s, new.limits.literal_window_s),
        ),
        # A token that lives longer links one value across more sessions.
        _compare(
            "token_ttl_s",
            old.token_ttl_s or no_expiry,
            new.token_ttl_s or no_expiry,
            shown=(old.token_ttl_s, new.token_ttl_s),
        ),
        # More rows in one answer, more equal tokens and labels to compare.
        _compare("limits.max_rows", old.limits.max_rows, new.limits.max_rows),
    ]
    if old.web_enabled != new.web_enabled:  # links make masks comparable; labels carry keys
        found.append(Change(WIDENED, "web_enabled", f"{old.web_enabled} -> {new.web_enabled}"))
    found.extend(
        Change(CHANGED, field, "the declaration applies to another database")
        for field in ("dsn_env", "dialect")
        if getattr(old, field) != getattr(new, field)
    )
    return [c for c in found if c is not None]


def _budget(where: str, before: object, after: object) -> Change | None:
    """Compare budgets: 0 turns the thing off, ``unlimited`` (or none) lifts the limit."""

    def amount(value: object) -> float:
        return float("inf") if value is None or value == UNLIMITED else float(str(value))

    def shown(value: object) -> object:
        return UNLIMITED if value is None else value

    return _compare(where, amount(before), amount(after), (shown(before), shown(after)))


def _compare(
    where: str, before: float, after: float, shown: tuple[object, object] | None = None
) -> Change | None:
    if before == after:
        return None
    was, now = shown or (before, after)
    return Change(_step(before, after), where, f"{was} -> {now}")
