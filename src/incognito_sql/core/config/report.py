"""What the protection profiles of a declaration open, said to the operator."""

from incognito_sql.core.config.model import Declaration
from incognito_sql.core.config.protection import PRESETS, opens, resolve, summary, warning


def protection_lines(decl: Declaration) -> list[str]:
    """Return a summary line per profile in use and a warning for each that widens the base."""
    names = [decl.protection]
    for cols in decl.column_protection.values():
        names.extend(name for name in cols.values() if name not in names)
    lines: list[str] = []
    beyond = set(opens(PRESETS["balanced"]))
    series = False
    for name in names:
        ops = resolve(name, decl.protections)
        lines.append(summary(name, ops))
        note = warning(name, decl.protections)
        if note is not None:
            lines.append(note)
        series = series or not beyond.issuperset(opens(ops))
    if series:
        lines.append(_series_warning(decl))
    return lines + _unlimited_warnings(decl)


def _series_warning(decl: Declaration) -> str:
    # The budgets are the only brake on a series of L3 tests.
    limits = decl.limits
    return (
        "warning: a series of L3 tests is a slow channel: only the budgets slow it, "
        f"{_amount(limits.literal_budget, 'literals')} and "
        f"{_amount(limits.probe_budget, 'probes')} in each "
        f"{limits.literal_window_s} s window, with no total cap"
    )


def _amount(budget: int | None, unit: str) -> str:
    return f"unlimited {unit}" if budget is None else f"{budget} {unit}"


def _unlimited_warnings(decl: Declaration) -> list[str]:
    # An unlimited budget is said like a profile wider than balanced.
    limits = decl.limits
    named = [
        ("literal_budget", limits.literal_budget, "the existence oracle and a series of L3 tests"),
        ("probe_budget", limits.probe_budget, "a series of L3 tests"),
    ]
    return [
        f"warning: limits.{key} is unlimited: nothing slows {what}; under a profile past "
        "balanced a value is read whole in minutes"
        for key, budget, what in named
        if budget is None
    ]


def protection_warnings(decl: Declaration) -> list[str]:
    """Return only the warnings of protection_lines."""
    return [line for line in protection_lines(decl) if line.startswith("warning:")]
