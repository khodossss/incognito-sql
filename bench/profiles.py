"""incognito-sql's protection profiles in both benchmarks: their rows and their claims.

Levels: L1, a hidden value shown whole; L2, a part of it; L3, a fact about it inferred
by a series of queries. A claim names the highest level a tool holds and the L3 channels
it leaves open. A competitor claims what its own README promises at the pinned version
(``COMPETITORS``): masking ones promise nothing about inference, so their claim is L1 with
every channel open, and a value a series recovers whole compares them at one level.
incognito-sql claims what the server declares for its profile (``protection.claims``):
L3 with the channels it opens, a value recovered by a series breaking any of its claims;
a row per profile is named ``incognito-sql (<mode>, <profile>)``, a row with none runs
the server's default profile. A row ``incognito-sql (<mode>, <profile>, no budget)``
runs the series with the literal budget lifted: a measurement of what a channel can
carry, with no claim.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from bench.adapters.base import Info
from incognito_sql.core.config import protection
from incognito_sql.levels.infer import CHANNELS

PROFILES = tuple(protection.claims())  # the ready profiles, as the server names them


NO_BUDGET = "no budget"


def row_name(name: str, profile: str) -> str:
    """Return the row of ``profile`` for incognito-sql's row ``name``."""
    return f"{name.removesuffix(')')}, {profile})"


@dataclass(frozen=True)
class Claim:
    """The highest level a tool holds, and the L3 channels it leaves open."""

    level: str  # "none", "L1", "L2" or "L3"
    open: frozenset[str] = frozenset(CHANNELS)
    series: bool = False  # a value recovered whole by a series breaks the claim too
    stated: bool = True  # False: the tool promises nothing definite, L1 is our reading
    source: str = field(default="", compare=False)  # the tool's own words, and where

    def label(self) -> str:
        """Return the claim as the report shows it."""
        if not self.stated:
            return f"{self.level} (no claim)"
        if self.level != "L3" or not self.open:
            return self.level
        return f"L3 but {', '.join(c for c in CHANNELS if c in self.open)}"


NONE = Claim("none")
MASKING = Claim("L1")
_LEVEL = "L3 "


def ours(declared: Mapping[str, Sequence[str]]) -> dict[str, Claim]:
    """Return incognito-sql's claim per profile from the leaks the server says it opens.

    Raise ValueError on a leak that is not an L3 channel: the claim would be read wrong.
    """
    out = {}
    for profile, leaks in declared.items():
        channels = {leak.removeprefix(_LEVEL) for leak in leaks}
        if not all(leak.startswith(_LEVEL) for leak in leaks) or not channels <= set(CHANNELS):
            msg = f"{profile}: leaks the benchmark does not judge: {sorted(leaks)}"
            raise ValueError(msg)
        out[profile] = Claim("L3", frozenset(channels), series=True)
    return out


CLAIMS = ours(protection.claims())
INCOGNITO = CLAIMS[protection.DEFAULT]  # the server with no profile named


_CLOSED = frozenset[str]()
# What each competitor promises in its own README at the pinned version (Info.version).
COMPETITORS = {
    "datacharter": Claim(
        "L1",
        source='README#L25 @a7cb14e (v0.44.0): "An agent sees `•••` where PII lives."',
    ),
    "mcp-db-results-anonymizer": Claim(
        "L1",
        source='README#L18 @6aa6ae3: "The agent never sees real data or connection credentials."',
    ),
    "dbmcp": Claim(
        "L1",
        stated=False,
        source='README#L345 @02682fd (v0.15.2): "PII redaction (opt-in, off by default)": '
        "a feature, no promise",
    ),
    "dbridge-mcp": Claim(
        "L1",
        source='README#L187 @5c7afee (v0.7.1): "Restricted columns can be hidden entirely: the '
        'model cannot see them in the schema, query them, or receive them in results."',
    ),
    "dbveil": Claim(
        "L1",
        source='README#security-model @4c60bf2 (v0.2.0): "PII never leaves your machine unmasked."',
    ),
    "db-mcp-server": Claim(
        "L1",
        stated=False,
        source='README#L121 @1b79050: "Redacts PII in query results by content shape": '
        "a feature, no promise",
    ),
    "gate": Claim(
        "L1",
        source='README#L38 @23073d9 (v0.11.6): "Redaction guarantee | 100% for configured tools"',
    ),
    "januscope": Claim(
        "L1",
        stated=False,
        source='README#L20 @31a915f (v0.5.0): "scrubs matching PII out of returned values before '
        'the model reads them": a feature, no promise',
    ),
    "keeper": Claim(
        "L1",
        source='README#L13 @c898050: "masks results on the way out"; #what-it-does-not-do: "It '
        'does not detect an agent inferring a masked value through narrowing predicates."',
    ),
    "mcp-server-conceal": Claim(
        "L1",
        stated=False,
        source='README#L3 @d984667 (v0.1.0): "pseudo-anonymizes PII before data reaches external '
        'AI providers": a feature, no promise',
    ),
    "mcp-pii-shield": Claim(
        "L1",
        source='README#L7 @0515340: "intercepts database query results to prevent sensitive data '
        'egress"',
    ),
    "safedb-mcp": Claim(
        "L1",
        source='README#security-guarantees @dab5ab0: "Configured PII fields are masked before tool '
        'responses are returned."',
    ),
    "sanitized-db-mcp": Claim(
        "L3",
        _CLOSED,
        series=True,  # a claim above L1 is judged as ours
        source='README#L288 @876c931: "WHERE/JOIN check ─── hidden column? → '
        'RestrictedColumnError"; #security-model: ORDER BY, GROUP BY "walked with WHERE rules"',
    ),
    "sql-safe-mcp": Claim(
        "L3",
        _CLOSED,
        series=True,  # a claim above L1 is judged as ours
        source='README#L230 @9dd2a69: "A token is accepted only in `=` and `IN` predicates"; "If '
        "`FirstName` is protected, `SELECT FirstName FROM Users WHERE FirstName = 'Alice'` is "
        'rejected"',
    ),
    "veil": Claim(
        "L1",
        source='README#L10 @d4476c4 (0.3.2): "veil makes sure the model never sees a real person."',
    ),
}


def measured(info: Info) -> bool:
    """Tell whether ``info`` is a row with the literal budget lifted: no claim, a measure."""
    return info.name.endswith(f", {NO_BUDGET})")


def claim_of(info: Info) -> Claim:
    """Return the claim of a tool: by its documentation, ours by its profile.

    A row of incognito-sql per profile is named ``incognito-sql (<mode>, <profile>)``.
    """
    if info.rung == 0 or measured(info):
        return NONE
    if not info.strict:
        return COMPETITORS.get(info.name, Claim("L1", stated=False, source="not read"))
    _, _, profile = info.name.rstrip(")").rpartition(", ")
    return CLAIMS.get(profile, INCOGNITO)
