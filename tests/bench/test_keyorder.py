"""Row objects with sorted keys come back in the query's select order."""

from bench.adapters.keyorder import object_rows, ordered, select_names


def test_keys_follow_aliases_columns_and_function_names() -> None:
    sql = "SELECT tier, COUNT(*), SUM(total) AS s FROM users GROUP BY tier"
    names = select_names(sql, "postgres")
    assert ordered(["count", "s", "tier"], names) == ["tier", "count", "s"]
    assert ordered(["COUNT(*)", "s", "tier"], names) == ["tier", "COUNT(*)", "s"]


def test_an_unmatched_key_fills_the_free_place() -> None:
    names = select_names("SELECT u.id, SUM(p.total) / COUNT(*) FROM users u", "postgres")
    assert ordered(["?column?", "id"], names) == ["id", "?column?"]


def test_unknown_shapes_keep_the_server_order() -> None:
    assert select_names("SELECT * FROM users", "sqlite") == []
    assert select_names("not sql at all (", "sqlite") == []
    assert ordered(["b", "a"], []) == ["b", "a"]


def test_rows_are_built_in_select_order() -> None:
    records = [{"count": 4, "tier": "x"}, {"count": 5, "tier": "y"}]
    sql = "SELECT tier, count(*) FROM users GROUP BY tier"
    assert object_rows(records, sql, "postgres") == [["x", 4], ["y", 5]]
    assert object_rows([], sql, "postgres") == []
    assert object_rows([1, 2], sql, "postgres") == [[1], [2]]
    assert object_rows(None, sql, "postgres") is None
