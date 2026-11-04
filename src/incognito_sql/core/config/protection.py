"""Protection profiles: which operations an identifier column admits, and what each opens."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Operation(StrEnum):
    """A use of an identifier value in a query; the keys of a profile's allow / deny."""

    OUTPUT = "output"
    EQ_TOKEN = "eq_token"  # noqa: S105
    EQ_LITERAL = "eq_literal"
    JOIN_IDENT = "join_ident"
    GROUP = "group"
    COUNT_DISTINCT = "count_distinct"
    IS_NULL = "is_null"
    LENGTH = "length"
    ORDER = "order"
    PREFIX = "prefix"
    CONTAINS = "contains"
    NE = "ne"


class Leak(StrEnum):
    """What the model can learn about a hidden value beyond the tokens it already sees."""

    EXISTENCE = "L3 existence"
    LENGTH = "L3 length"
    ORDER = "L3 order"
    PREFIX = "L3 prefix"
    CONTAINS = "L3 contains"


# An operation absent here opens nothing: equality of values is already visible
# through equal tokens, and a null through the selected column, which shows it as null.
OPENS: dict[Operation, Leak] = {
    Operation.EQ_LITERAL: Leak.EXISTENCE,
    Operation.LENGTH: Leak.LENGTH,
    Operation.ORDER: Leak.ORDER,
    Operation.PREFIX: Leak.PREFIX,
    Operation.CONTAINS: Leak.CONTAINS,
    Operation.NE: Leak.EXISTENCE,
}

BASE = frozenset(
    {
        Operation.OUTPUT,
        Operation.EQ_TOKEN,
        Operation.EQ_LITERAL,
        Operation.JOIN_IDENT,
        Operation.GROUP,
        Operation.COUNT_DISTINCT,
    }
)
# Presets and the default.
# balanced adds what opens no new channel; permissive gains operations release by release.
PRESETS: dict[str, frozenset[Operation]] = {
    "strict": BASE,
    "balanced": BASE | {Operation.IS_NULL},
    "permissive": BASE
    | {
        Operation.IS_NULL,
        Operation.LENGTH,
        Operation.ORDER,
        Operation.PREFIX,
        Operation.CONTAINS,
        Operation.NE,
    },
}
DEFAULT = "permissive"
_GROWING = "permissive"


class CustomProfile(BaseModel):
    """An operator's profile: a preset with operations added and removed."""

    model_config = ConfigDict(extra="forbid")

    extends: str
    allow: list[Operation] = []
    deny: list[Operation] = []


def resolve(name: str, custom: dict[str, CustomProfile]) -> frozenset[Operation]:
    """Return the operations of a preset or custom profile; raise ValueError if unknown."""
    if name in PRESETS:
        return PRESETS[name]
    if name not in custom:
        msg = f"unknown protection profile: {name}"
        raise ValueError(msg)
    profile = custom[name]
    if profile.extends not in PRESETS:
        msg = f"profile {name} extends {profile.extends}, which is not a preset"
        raise ValueError(msg)
    return (PRESETS[profile.extends] | set(profile.allow)) - set(profile.deny)


def check_names(custom: dict[str, CustomProfile]) -> None:
    """Raise ValueError if a custom profile shadows a preset or extends a non-preset."""
    for name in custom:
        if name in PRESETS:
            msg = f"profile {name} has the name of a preset"
            raise ValueError(msg)
        resolve(name, custom)


def opens(ops: frozenset[Operation]) -> list[Leak]:
    """Return the leaks a set of operations opens, in a stable order."""
    return sorted({OPENS[op] for op in ops if op in OPENS})


def claims() -> dict[str, list[str]]:
    """Return, for each preset, the leaks it opens: the claim a benchmark judges it by.

    A leak not listed is one the preset claims to close. No profile shows a whole value
    (L1) in an answer; a series of L3 tests can rebuild one within the literal budget.
    """
    return {name: [str(leak) for leak in opens(ops)] for name, ops in PRESETS.items()}


def summary(name: str, ops: frozenset[Operation]) -> str:
    """Return one line: the profile, what it never shows, and what it opens."""
    leaks = ", ".join(opens(ops)) or "nothing"
    return f"protection: {name} - never shows an identifier value whole; opens {leaks}"


def warning(name: str, custom: dict[str, CustomProfile]) -> str | None:
    """Return a warning if the profile admits more than balanced or follows permissive."""
    extra = sorted(resolve(name, custom) - PRESETS["balanced"])
    grows = name == _GROWING or (name in custom and custom[name].extends == _GROWING)
    if not extra and not grows:
        return None
    parts = []
    if extra:
        named = ", ".join(f"{op} ({OPENS[op]})" if op in OPENS else str(op) for op in extra)
        parts.append(f"admits more than balanced: {named}")
    if grows:
        parts.append(
            "follows permissive, which admits more as releases add operations"
            " (next: part of a value in the output)"
        )
    return (
        f"warning: protection {name} {'; '.join(parts)}; "
        "set `protection: balanced` in the config for a fixed, narrower set"
    )
