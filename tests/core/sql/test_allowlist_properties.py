import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlglot import exp

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import ALLOWED_ARGS, check_nodes
from incognito_sql.core.sql.parse import parse


def all_expression_classes() -> list[type[exp.Expr]]:
    seen: set[type[exp.Expr]] = {exp.Expr}
    stack: list[type[exp.Expr]] = [exp.Expr]
    while stack:
        for sub in stack.pop().__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    return sorted(seen, key=lambda c: (c.__module__, c.__qualname__))


def instantiable(cls: type[exp.Expr]) -> bool:
    try:
        cls()
    except Exception:  # noqa: BLE001
        return False
    return True


def reason_of(tree: exp.Expression) -> Reason | None:
    try:
        check_nodes(tree)
    except Rejection as exc:
        return exc.reason
    return None


def projection_of(node: exp.Expr) -> exp.Expression:
    tree = parse("SELECT a FROM people", "postgres", Limits())
    tree.set("expressions", [node])
    return tree


UNLISTED = [c for c in all_expression_classes() if c not in ALLOWED_ARGS and instantiable(c)]


def test_enumeration_is_broad() -> None:
    assert len(UNLISTED) > 900
    assert exp.Expr in UNLISTED  # Expr-only bases are exercised too
    assert exp.Func in UNLISTED


@pytest.mark.parametrize("cls", UNLISTED, ids=lambda c: c.__name__)
def test_every_unlisted_sqlglot_node_is_rejected(cls: type[exp.Expr]) -> None:
    assert reason_of(projection_of(cls())) == Reason.NODE_NOT_ALLOWED


UNLISTED_ARGS = [
    (cls, arg)
    for cls, allowed in ALLOWED_ARGS.items()
    for arg in sorted(set(cls.arg_types) - allowed)
]


@pytest.mark.parametrize(
    ("cls", "arg"), UNLISTED_ARGS, ids=lambda v: v if isinstance(v, str) else v.__name__
)
def test_every_unlisted_arg_is_rejected(cls: type[exp.Expr], arg: str) -> None:
    assert reason_of(projection_of(cls(**{arg: True}))) == Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize("cls", list(ALLOWED_ARGS), ids=lambda c: c.__name__)
def test_allowed_args_are_real_sqlglot_args(cls: type[exp.Expr]) -> None:
    assert ALLOWED_ARGS[cls] <= set(cls.arg_types)


def test_empty_args_are_ignored() -> None:
    node = exp.Column(this=exp.to_identifier("a"), db=None, catalog=[], join_mark=False)
    assert reason_of(projection_of(node)) is None


# Each template: (space-separated tokens, verdict). Upper-case tokens are keywords;
# {0} and {1} are aliases.
TEMPLATES: list[tuple[str, Reason | None]] = [
    ("SELECT {0}.city AS {1} FROM people AS {0}", None),
    (
        "SELECT COUNT(*) AS {1} FROM people {0} JOIN orders o ON o.pid = {0}.id GROUP BY {0}.city",
        None,
    ),
    ("WITH {0} AS (SELECT a FROM t) SELECT a AS {1} FROM {0} UNION ALL SELECT b FROM u", None),
    ("SELECT ROW_NUMBER() OVER () AS {1} FROM people {0}", None),
    ("SELECT {0}.a AS {1} FROM pg_catalog.pg_user {0}", Reason.SYSTEM_CATALOG),
    ("SELECT {0}.a AS {1} FROM t {0} INTERSECT SELECT b FROM u", None),
]

# Aliases carry a q_ prefix: an alias like pg_x used as a table name legitimately
# yields SYSTEM_CATALOG, and a bare keyword would not parse.
aliases = st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True).map(lambda s: "q_" + s)
spaces = st.sampled_from([" ", "  ", "\n", "\t", " \n "])
case = st.sampled_from([str.upper, str.lower, str.title])


@given(
    index=st.integers(0, len(TEMPLATES) - 1),
    names=st.lists(aliases, min_size=2, max_size=2, unique=True),
    data=st.data(),
)
def test_aliases_and_formatting_do_not_change_decision(
    index: int, names: list[str], data: st.DataObject
) -> None:
    tokens, verdict = TEMPLATES[index]
    rendered = []
    for token in tokens.split(" "):
        text = token.format(*names)
        if token.isupper():
            text = data.draw(case)(text)
        rendered.append(text + data.draw(spaces))
    sql = "".join(rendered)
    try:
        decision = reason_of(parse(sql, "postgres", Limits()))
    except Rejection as exc:
        decision = exc.reason
    assert decision == verdict
