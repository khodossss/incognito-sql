"""Query forms with a possible channel: the database's protection profile admits them."""

from enum import StrEnum

from incognito_sql.core.config.protection import CustomProfile


class Form(StrEnum):
    """A query form with a possible channel: the database's profile decides it."""

    NULLABLE_KEY_GROUP = "nullable_key_group"
    COMPUTED_SUM = "computed_sum"
    WINDOW = "window"
    SPELLING_CHOICE = "spelling_choice"
    FALLIBLE_SUBQUERY = "fallible_subquery"
    FLOAT_SUM = "float_sum"


# Forms with a possible channel:
# a column outside GROUP BY over a key that can hold NULL reads whichever NULL-key row
# the scan meets first; SUM / AVG of a computed value can overflow at a point that
# depends on the order rows are added; a window numbers tied rows in scan order.
# The scan-order residue is closed by strict only: which of equal values'
# spellings an answer shows, an error inside a subquery that may stop at its first row,
# the rounding of a float sum.
_SCAN_ORDER = frozenset({Form.SPELLING_CHOICE, Form.FALLIBLE_SUBQUERY, Form.FLOAT_SUM})
FORMS: dict[str, frozenset[Form]] = {
    "strict": frozenset(),
    "balanced": _SCAN_ORDER,
    "permissive": frozenset(Form),
}


def forms(name: str, custom: dict[str, CustomProfile]) -> frozenset[Form]:
    """Return the query forms a profile admits: those of its preset."""
    return FORMS[name] if name in FORMS else FORMS[custom[name].extends]
