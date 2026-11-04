"""The competitors the benchmark runs: modules with ``INFO``, ``DIALECTS``, ``open_adapter``."""

from types import ModuleType

from bench.adapters import (
    conceal,
    datacharter,
    db_results_anonymizer,
    dbmcp,
    dbridge_mcp,
    dbveil,
    freepeak_db_mcp,
    gate,
    januscope,
    keeper,
    mcp_pii_shield,
    safedb_mcp,
    sanitized_db_mcp,
    sql_safe_mcp,
    veil,
)

COMPETITORS: tuple[ModuleType, ...] = (
    conceal,
    datacharter,
    db_results_anonymizer,
    dbmcp,
    dbridge_mcp,
    dbveil,
    freepeak_db_mcp,
    gate,
    januscope,
    keeper,
    mcp_pii_shield,
    safedb_mcp,
    sanitized_db_mcp,
    sql_safe_mcp,
    veil,
)
