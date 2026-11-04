"""What a profile without the scan-order forms refuses: results that follow the scan order.

An index on an identifier column makes the DBMS visit rows in the order of its values,
so anything decided by which row comes first carries that order.
"""

from sqlglot import exp

from incognito_sql.core.config.forms import Form, forms
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.flows import flows
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.scan_fallible import check_fallible
from incognito_sql.core.sql.scan_spellings import check_spellings
from incognito_sql.core.sql.typefamily import base_type

_FLOATS = frozenset({"REAL", "FLOAT", "FLOAT4", "FLOAT8", "DOUBLE"})
# Collations that compare different spellings equal by default.
_CASE_BLIND = frozenset({"mysql", "tsql"})


def check_scan_order(tree: exp.Expr, lin: Lineage, catalog: Catalog) -> None:
    """Refuse what the scan order decides, for each form the profile does not admit."""
    admitted = forms(lin.decl.protection, lin.decl.protections)
    if Form.FLOAT_SUM not in admitted:
        _check_float_sums(tree, lin, catalog)
    if Form.FALLIBLE_SUBQUERY not in admitted:
        check_fallible(tree, lin, catalog)
    if Form.SPELLING_CHOICE not in admitted and lin.decl.dialect in _CASE_BLIND:
        check_spellings(tree, lin, catalog)


def _check_float_sums(tree: exp.Expr, lin: Lineage, catalog: Catalog) -> None:
    # A float sum rounds differently in another order of addition. A SQLite NUMERIC column
    # may hold floats too; the output keeps 12 significant digits of them.
    for agg in tree.find_all(exp.Sum, exp.Avg):
        for ref in flows(lin, agg.this):
            column_type = catalog.columns.get(ref.table, {}).get(ref.column)
            if column_type is not None and _holds_floats(column_type):
                raise Rejection(Reason.FLOAT_AGGREGATE)


def _holds_floats(column_type: str) -> bool:
    # A declared float type; SQLite's REAL affinity is any type naming REAL, FLOA or DOUB.
    upper = column_type.upper()
    return base_type(column_type) in _FLOATS or any(n in upper for n in ("REAL", "FLOA", "DOUB"))
