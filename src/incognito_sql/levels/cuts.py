"""The L2 cases of a hidden column: queries that cut a piece out of its values.

One query per form: the head and the tail of the value, as long as a piece must be to
count (``incognito_sql.levels.fragment``), the value cut in two around a separator, and
``MIN``/``MAX``, which return values whole. A case that shows a value whole is an L1
leak, one that shows a piece is L2. The queries are built as trees and written in the
database's dialect: no negative start of a substring, no ``GREATEST``, integer division,
and a length that keeps trailing spaces (``incognito_sql.levels.dialects``).
"""

from sqlglot import exp

from incognito_sql.levels.dialects import written

ROWS = 20  # rows a case asks for: enough to show pieces, few for the oracle
_SHORT = 11  # below this length a piece needs 6 characters; from it, half the value


def _half(length: exp.Expr) -> exp.Expr:
    half = exp.IntDiv(this=exp.paren(length + 1), expression=exp.Literal.number(2))
    return exp.cast(half, "INT")  # PostgreSQL's DIV is numeric, SUBSTRING wants an integer


def _forms(c: exp.Column) -> dict[str, exp.Expr]:
    length = exp.Length(this=c.copy())
    need = exp.Case(
        ifs=[exp.If(this=length.copy() < _SHORT, true=exp.Literal.number(6))],
        default=_half(length.copy()),
    )
    start = exp.Case(
        ifs=[exp.If(this=length.copy() > need.copy(), true=length.copy() - need.copy() + 1)],
        default=exp.Literal.number(1),
    )
    half = _half(length.copy())
    return {
        "head": exp.Substring(this=c.copy(), start=exp.Literal.number(1), length=need),
        "tail": exp.Substring(this=c.copy(), start=start, length=need.copy()),
        "split": exp.DPipe(
            this=exp.DPipe(
                this=exp.Substring(this=c.copy(), start=exp.Literal.number(1), length=half),
                expression=exp.Literal.string(" | "),
            ),
            expression=exp.Substring(this=c.copy(), start=half.copy() + 1, length=length),
        ),
    }


def cuts(table: str, column: str, dialect: str) -> list[tuple[str, str]]:
    """Return (case, query) for one hidden column, written in ``dialect``."""
    c = exp.column(column, quoted=True)
    source = exp.table_(table, quoted=True)
    present = exp.Not(this=exp.Is(this=c.copy(), expression=exp.Null()))
    name = f"{table}.{column}"
    out = []
    for form, expression in _forms(c).items():
        query = exp.select(expression).from_(source.copy()).where(present.copy()).limit(ROWS)
        out.append((f"{name}:{form}", written(query, dialect)))
    extremes = exp.select(exp.Min(this=c.copy()), exp.Max(this=c.copy()))
    out.append((f"{name}:minmax", written(extremes.from_(source).where(present), dialect)))
    return out
