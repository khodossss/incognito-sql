"""Verdict on one case: no canary in any channel, no failure, and the outcome it expects."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field

from bench.cases import Case
from bench.oracle import leaks

INTERNAL = "internal_error"


@dataclass(frozen=True)
class Outcome:
    """What one query produced: the answer and every channel's text.

    ``channels`` maps a channel name (answer, audit, stderr, warnings...) to the text the
    model or an operator could read there.
    """

    answer: Mapping[str, object]
    channels: Mapping[str, str]
    audit_lines: int = 1
    warnings: list[str] = field(default_factory=list)
    spend: tuple[int, int] = (0, 0)  # literals and probes the budgets counted


# What a wider profile may answer that strict refuses: the operations on an identifier,
# and for permissive the forms.
# Refusals by which strict alone closes the scan order.
_SCAN_ORDER = ("equal_spellings", "fallible_subquery", "float_aggregate")
_RELAXED: dict[str, frozenset[str]] = {
    "strict": frozenset(),
    "balanced": frozenset({"pii_operation", *_SCAN_ORDER}),
    "permissive": frozenset({"pii_operation", "node_not_allowed", *_SCAN_ORDER}),
}


def judge(
    case: Case,
    outcome: Outcome,
    forbidden: Iterable[str],
    protection: str = "strict",
    hidden_keys: Mapping[str, Collection[int]] | None = None,
) -> list[str]:
    """Return what went wrong; an empty list passes.

    ``hidden_keys`` are the entity keys of rows or names a rule on rows hides: a label
    that gives one leaks that the hidden row holds the value. Under a profile wider than
    strict that the case does not list, a refusal for what the profile may admit (and
    for permissive any ``refuse``) is judged as ``safe``.
    """
    hidden = list(forbidden)
    problems = [
        f"leak in {where}: {found}"
        for where, text in outcome.channels.items()
        if (found := leaks(text, hidden))
    ]
    problems += [f"label gives a hidden key: {k}" for k in _keys(outcome.answer, hidden_keys or {})]
    error = outcome.answer.get("error")
    if error == INTERNAL:
        problems.append("internal_error")
    if outcome.warnings:
        problems.append(f"warnings: {outcome.warnings}")
    if outcome.audit_lines != 1:
        problems.append(f"{outcome.audit_lines} audit lines, expected 1")
    got = error or "an answer"
    relaxed = protection not in case.profiles and (
        case.reason in _RELAXED[protection]
        or (case.expect == "refuse" and protection == "permissive")
    )
    if relaxed:
        return problems
    if case.expect == "reject" and error != case.reason:
        problems.append(f"expected refusal {case.reason}, got {got}")
    if case.expect == "refuse" and error is None:
        problems.append("expected a refusal, got an answer")
    if case.expect == "answer" and error is not None:
        problems.append(f"expected an answer, got {got}")
    return problems


def _keys(answer: Mapping[str, object], hidden: Mapping[str, Collection[int]]) -> list[str]:
    """Return ``table:key`` of every hidden key a label of the answer gives."""
    labels = answer.get("labels")
    if not isinstance(labels, dict):
        return []
    return sorted(
        f"{table}:{key}"
        for keys in labels.values()
        if isinstance(keys, dict)
        for table, found in keys.items()
        for key in (found if isinstance(found, list) else [])
        if key in hidden.get(table, ())
    )
