"""Put the keys of an answer's row objects back in the order the query selects them.

A tool that answers with JSON objects whose keys come sorted (dbmcp: serde_json without
``preserve_order``) loses the column order the model asked for; the model reads the keys
by name, the benchmark compares rows by position. Each output key is matched to a select
item by its alias or column name, its SQL text, or its function name (``count``);
unmatched keys fill the remaining places in their own order.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from bench.adapters.base import Rows


def select_names(sql: str, dialect: str) -> list[set[str]]:
    """Return, per select item, the names its output key may carry; empty if unknown."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except SqlglotError:
        return []
    if not isinstance(tree, exp.Query) or any(isinstance(e, exp.Star) for e in tree.selects):
        return []
    names = []
    for item in tree.selects:
        inner = item.this if isinstance(item, exp.Alias) else item
        names.append({item.alias_or_name.lower(), inner.sql(dialect=dialect).lower(), inner.key})
    return names


def ordered(keys: list[str], names: list[set[str]]) -> list[str]:
    """Return ``keys`` in select order; unchanged when the counts differ."""
    if len(keys) != len(names):
        return keys
    places: list[str | None] = [None] * len(names)
    rest = []
    for key in keys:
        free = [i for i, n in enumerate(names) if places[i] is None and key.lower() in n]
        if free:
            places[free[0]] = key
        else:
            rest.append(key)
    left = iter(rest)
    return [p if p is not None else next(left) for p in places]


def object_rows(records: object, sql: str, dialect: str) -> Rows | None:
    """Turn a JSON list of row objects into rows, columns in the query's select order."""
    if not isinstance(records, list):
        return None
    if not records or not all(isinstance(r, dict) for r in records):
        return [[r] for r in records]
    keys = ordered(list(records[0]), select_names(sql, dialect))
    return [[r.get(k) for k in keys] for r in records]
