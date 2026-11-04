"""One verdict for the benchmark and assess: leaks by level against a claim."""

from incognito_sql.levels.dialects import translated
from incognito_sql.levels.verdict import Leaks, verdict

NONE = Leaks(shown=False, read_whole=False, parts=False, inferred=frozenset())


def test_a_claim_is_broken_level_by_level() -> None:
    assert verdict(NONE, "none", frozenset()) == "no claim"
    assert verdict(NONE, "L3", frozenset()) == "holds"
    assert verdict(NONE, "L1", frozenset()).startswith("holds L1")
    read = Leaks(shown=False, read_whole=True, parts=True, inferred=frozenset({"length"}))
    assert verdict(read, "L3", frozenset()) == "breaks L1; L2; L3 (length)"
    assert verdict(read, "L3", frozenset({"length"})) == "breaks L1; L2"
    assert verdict(read, "L1", frozenset(), series=False).startswith("holds L1")  # masking


def test_sql_server_counts_trailing_spaces_in_a_length() -> None:
    sql = "SELECT count(*) FROM t WHERE length(max(c)) > 3"
    assert "(LEN(CONCAT(MAX(c), 'x')) - 1) > 3" in translated(sql, "tsql")
    assert translated(sql, "sqlite") == sql
    assert "LEN(" not in translated(sql, "postgres")


def test_like_ignores_case_wherever_it_is_asked() -> None:
    sql = "SELECT count(*) FROM t WHERE c LIKE 'av%'"
    assert "ILIKE 'av%'" in translated(sql, "postgres")
    assert "ILIKE 'av%'" in translated(sql, "duckdb")
    assert "ILIKE" not in translated(sql, "mysql")
