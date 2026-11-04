"""How many L3 probes of identifier values a query holds."""

import pytest
import sqlglot
from sqlglot.optimizer.qualify import qualify

from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.probe_count import count_probes

from .conftest import CATALOG, DECL, SCHEMA


@pytest.mark.parametrize(
    ("sql", "probes"),
    [
        ("SELECT id FROM people WHERE full_name > 'M'", 1),
        ("SELECT id FROM people WHERE full_name BETWEEN 'A' AND 'M' AND phone <> 5", 2),
        ("SELECT id FROM people WHERE full_name LIKE 'A%'", 1),
        ("SELECT length(full_name) FROM people", 1),
        ("SELECT max(full_name), min(phone) FROM people", 2),
        ("SELECT id FROM people ORDER BY full_name", 1),
        ("SELECT p.id FROM people p JOIN orders o ON p.full_name > o.customer_name", 1),
        ("SELECT id FROM people WHERE 'K' BETWEEN full_name AND phone", 1),
        ("SELECT id FROM people WHERE full_name = 'Ivan Petrov'", 0),
        ("SELECT id FROM people WHERE id > 3 ORDER BY city", 0),
        ("SELECT full_name, count(*) FROM people GROUP BY full_name", 0),
    ],
)
def test_each_node_that_probes_an_identifier_counts_once(sql: str, probes: int) -> None:
    tree = qualify(sqlglot.parse_one(sql, read="postgres"), schema=SCHEMA, dialect="postgres")
    assert count_probes(tree, Lineage(tree, CATALOG, DECL)) == probes
