"""What the agent may do after a refusal: a `retry` and a constant `hint` for each reason.

The core answers a refusal with its reason only; this layer adds, for the agent, whether
to rewrite the query (`rewrite`), ask the human (`ask_user`) or give up on this question
(`stop`), and one fixed sentence per reason. A hint names no value, no column and no
database text: it is the same for every refusal with that reason.
"""

from enum import StrEnum


class Retry(StrEnum):
    """The agent's next step after a refusal."""

    REWRITE = "rewrite"  # the agent can fix the query itself, within what `describe` allows
    ASK_USER = "ask_user"  # only a human can lift it: a literal budget, a protection profile
    STOP = "stop"  # final for this question


# Keyed by the reason's value: an entry may precede its reason in the core by a merge.
GUIDE: dict[str, tuple[Retry, str]] = {
    "parse_error": (
        Retry.REWRITE,
        "The SQL could not be parsed. Write it in the dialect `describe` names.",
    ),
    "multiple_statements": (
        Retry.REWRITE,
        "Send one statement per call.",
    ),
    "limit_exceeded": (
        Retry.REWRITE,
        (
            "The query is too large: too long, too many nodes, joins or IN items, or more "
            "values than the database takes as parameters. Simplify or split it."
        ),
    ),
    "node_not_allowed": (
        Retry.REWRITE,
        (
            "Only one read-only SELECT, WITH ... SELECT, UNION, INTERSECT or EXCEPT runs, and "
            "some syntax inside it is not accepted (LIMIT and OFFSET take integer literals "
            "only; a `*` reads base tables only). Rewrite it with plainer SQL."
        ),
    ),
    "unknown_column": (
        Retry.REWRITE,
        (
            "A table or column name is not known, or a `*` cannot be expanded there (in a "
            "branch of UNION, INTERSECT or EXCEPT, or with no table). Take the names from "
            "`describe` and list them."
        ),
    ),
    "ambiguous_column": (
        Retry.REWRITE,
        (
            "A column name does not resolve to exactly one usable column, or an alias repeats "
            "the name of a column of a table in the query. Qualify the column with its table "
            "or alias, or rename the alias, and take the names from `describe`."
        ),
    ),
    "hidden_column": (
        Retry.REWRITE,
        (
            "The query names a column that `describe` does not list: it is hidden and cannot "
            "be queried in any form. Answer without it; only the operator can open it."
        ),
    ),
    "pii_operation": (
        Retry.REWRITE,
        (
            "An identifier column is used in a way its protection profile does not allow. Use "
            "only the operations `describe` lists; if the question needs more, tell the user. "
            "Rewording the same question to get the value in another shape is not a fix."
        ),
    ),
    "pii_join_with_open": (
        Retry.REWRITE,
        (
            "An identifier column is compared with a column that is not an identifier. Compare "
            "it only with a token, a literal the user gave you, or another identifier column."
        ),
    ),
    "literal_type_mismatch": (
        Retry.REWRITE,
        (
            "A literal or column compared with an identifier does not have its type. Use a "
            "token, or a literal of the column's type."
        ),
    ),
    "invalid_token": (
        Retry.REWRITE,
        "A token is unknown, expired or cut short. Take a fresh one from a recent answer.",
    ),
    "literal_budget": (
        Retry.ASK_USER,
        (
            "The limit of distinct literals compared with identifiers is reached: per session "
            "it does not refill, for the whole installation it frees up within the hour. "
            "Tokens from earlier answers still work; for a new literal, tell the user."
        ),
    ),
    "literals_off": (
        Retry.REWRITE,
        (
            "Literals compared with personal columns are turned off by the operator. "
            "Find the row through open columns and use its token."
        ),
    ),
    "probe_budget": (
        Retry.ASK_USER,
        (
            "Too many probes of identifier columns this hour across the installation: each <, "
            ">, BETWEEN, <>, LIKE, ORDER BY, MIN/MAX or length() over one counts. Sort or "
            "filter by an open column instead, or wait; if the question needs the probes, "
            "tell the user."
        ),
    ),
    "probes_off": (
        Retry.REWRITE,
        (
            "Comparing or sorting by personal columns is turned off by the operator: <, >, "
            "BETWEEN, <>, LIKE, ORDER BY, MIN/MAX and length() over them. Sort or filter by "
            "an open column instead; = and IN with a token still work."
        ),
    ),
    "rate_limit": (
        Retry.ASK_USER,
        (
            "Too many queries for now: the installation answers a fixed number per minute. "
            "Wait a minute, or ask the user whether this many queries are needed."
        ),
    ),
    "system_catalog": (
        Retry.REWRITE,
        "System catalogs and system schemas are closed. Use `describe` for the schema.",
    ),
    "float_aggregate": (
        Retry.REWRITE,
        (
            "SUM or AVG over a column declared floating-point can depend on the order rows "
            "are added. Sum or average an integer or DECIMAL column; a wider profile is the "
            "operator's choice."
        ),
    ),
    "fallible_subquery": (
        Retry.REWRITE,
        (
            "A computation that can fail on some values (arithmetic, CAST, abs, round, substr, "
            "a date function) runs inside EXISTS, IN (SELECT ...), a scalar subquery or WITH. "
            "Move it to the outer query, or into an aggregate without GROUP BY."
        ),
    ),
    "equal_spellings": (
        Retry.ASK_USER,
        (
            "On MySQL and SQL Server, the strict profile does not group, deduplicate or take "
            "MIN/MAX of open text: the database may pick among equal spellings in an order "
            "that follows an identifier. Ask the operator for another profile."
        ),
    ),
    "hidden_rows": (
        Retry.REWRITE,
        (
            "An expression that can fail, anywhere in a query over a table with hidden "
            "rows. Aggregate the plain column instead."
        ),
    ),
    "db_error": (
        Retry.REWRITE,
        (
            "The database refused or did not finish the statement; `sqlstate` (Postgres and "
            "MySQL only) and `detail`, when present, say why. Fix or simplify the SQL for this "
            "DBMS once; if it fails again, tell the user."
        ),
    ),
    "internal_error": (
        Retry.STOP,
        "The server failed on this query. Tell the user; the operator can read the server log.",
    ),
}


def explained(answer: dict[str, object]) -> dict[str, object]:
    """Return ``answer`` with `retry` and `hint` added when it is a refusal."""
    error = answer.get("error")
    if not isinstance(error, str) or error not in GUIDE:
        return answer
    retry, hint = GUIDE[error]
    return {**answer, "retry": retry.value, "hint": hint}
