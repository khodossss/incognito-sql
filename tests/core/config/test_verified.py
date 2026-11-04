"""`verified_open`: open or quasi columns a human checked, in lower case."""

import pytest
from pydantic import ValidationError

from incognito_sql.core.config import Declaration, verified_columns

BASE = {
    "dsn_env": "DSN",
    "dialect": "sqlite",
    "entities": [],
    "columns": {"orders": {"id": "open", "note": "quasi", "name": "identifier"}},
}


def test_verified_columns_are_lowered() -> None:
    decl = Declaration.model_validate(BASE | {"verified_open": {"Orders": ["ID", "Note"]}})
    assert verified_columns(decl) == {"orders.id", "orders.note"}
    assert verified_columns(Declaration.model_validate(BASE)) == frozenset()


@pytest.mark.parametrize("column", ["name", "missing"])
def test_only_open_or_quasi_columns_can_be_verified(column: str) -> None:
    with pytest.raises(ValidationError, match=f"orders.{column} is not an open or quasi"):
        Declaration.model_validate(BASE | {"verified_open": {"orders": [column]}})
