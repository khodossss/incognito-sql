"""Changes in the rules on rows: a rule that hides less opens rows to the model.

A rule is matched by its table and its condition, compared as sqlglot writes it back.
Whether a changed condition covers more rows or fewer is not worked out: the old rule
reads as gone (WIDENED) and the new one as added (NARROWED), so a pipeline stops it until
someone chooses it.
"""

from sqlglot.errors import ParseError

from incognito_sql.core.config import Declaration
from incognito_sql.core.config.row_rules import RowRule, condition
from incognito_sql.diff.kinds import NARROWED, WIDENED, Change

ALL = "*"


def rule_changes(old: Declaration, new: Declaration) -> list[Change]:
    """Return a change per rule gone, added, or hiding other columns."""
    before, after = _keyed(old.row_rules, old.dialect), _keyed(new.row_rules, new.dialect)
    gone = WIDENED, "rule gone or its condition changed"
    added = NARROWED, "rule added or its condition changed"
    found = [_change(key, *gone) for key in before.keys() - after.keys()]
    found += [_change(key, *added) for key in after.keys() - before.keys()]
    hidden = (_hidden(key, before[key], after[key]) for key in before.keys() & after.keys())
    return found + [c for c in hidden if c is not None]


def _change(key: tuple[str, str], kind: str, what: str) -> Change:
    return Change(kind, _where(key), f"{what}: {key[1]}")


def _keyed(rules: list[RowRule], dialect: str) -> dict[tuple[str, str], frozenset[str]]:
    """Map (table, condition) to the columns hidden; ``*`` hides the row."""
    out: dict[tuple[str, str], frozenset[str]] = {}
    for rule in rules:
        key = (rule.table.lower(), _condition(rule, dialect))
        hide = frozenset({ALL}) if rule.hide == ALL else frozenset(c.lower() for c in rule.hide)
        out[key] = out.get(key, frozenset()) | hide
    return out


def _condition(rule: RowRule, dialect: str) -> str:
    """Return the condition as sqlglot writes it back, or as written if it does not parse.

    Spacing outside literals is lost; a literal is kept as it is.
    """
    try:
        return condition(rule, dialect).sql()
    except ParseError:
        return rule.where


def _hidden(key: tuple[str, str], was: frozenset[str], now: frozenset[str]) -> Change | None:
    if was == now:
        return None
    if ALL in now:  # the whole row hidden now: nothing opens
        return Change(NARROWED, _where(key), f"hides more where {key[1]}")
    if ALL in was or not was <= now:  # the row, or a column, no longer hidden
        opened = ALL if ALL in was else ", ".join(sorted(was - now))
        return Change(WIDENED, _where(key), f"hides less ({opened}) where {key[1]}")
    return Change(NARROWED, _where(key), f"hides more where {key[1]}")


def _where(key: tuple[str, str]) -> str:
    return f"row_rules.{key[0]}"
