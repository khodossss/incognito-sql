"""Configurations of the masking competitors on a set's file, written from our marking.

Each follows the tool's configuration for our own world (``bench/adapters/config/``), with
that world's personal columns replaced by the columns a work does not show: identifiers,
free text, secrets and columns left out. db-mcp-server, gate, JanuScope and dbridge-mcp
match the column name of an answer and know no table; names go in as stored, in lower and
in upper case, wherever a tool matches case (dbridge-mcp does not).
"""

import json
import re

import yaml

from bench.external.marking import SHOWN
from bench.external.safedb import spellings
from bench.external.work import Work

# JanuScope: `**.name` would also redact every tool's name in the tool listing; rows sit at
# the answer's root, so the bare key is matched there instead (config/januscope.*.yaml).
_LISTING_KEYS = frozenset({"name"})
_WRITES = ("write", "insert", "update", "delete", "drop", "create", "alter", "truncate")
_PRISMA_TYPES = (("INT", "Int"), ("REAL", "Float"), ("FLOA", "Float"), ("DOUB", "Float"))
_PII_KINDS = (("email", "email"), ("phone", "phone"), ("name", "name"))
_UNSAYABLE = frozenset({"secret", "hidden"})  # dbridge-mcp: refused wherever named


def protected(work: Work) -> dict[str, dict[str, str]]:
    """Return {table: {column: class}} of every column the work does not show."""
    m = work.marking
    found = {
        t: {c: m.cls(t, c) for c in cols if m.cls(t, c) not in SHOWN}
        for t, cols in work.schema.items()
    }
    return {t: cols for t, cols in found.items() if cols}


def _names(work: Work) -> list[str]:
    columns = (c for cols in protected(work).values() for c in cols)
    return list(dict.fromkeys(s for c in columns for s in spellings(c)))


def freepeak(work: Work) -> str:
    """Return db-mcp-server's JSON: masks by column name (case-blind) and ``mask_pii``."""
    by_cls: dict[str, set[str]] = {"fixed_string": set(), "null": set()}
    for cols in protected(work).values():
        for column, cls in cols.items():
            by_cls["null" if cls == "secret" else "fixed_string"].add(re.escape(column))
    rules = [
        {"pattern": f"(?i)^({'|'.join(sorted(names))})$", "strategy": strategy}
        | ({"value": "***MASKED***"} if strategy == "fixed_string" else {})
        for strategy, names in by_cls.items()
        if names
    ]
    connection = {
        "id": "world",  # the tool is named after it: query_world
        "type": "sqlite",
        "database_path": f"/data/{work.path.name}",
        "read_only": True,
        "max_rows": 1000,
        "query_timeout": 10,
        "mask_pii": True,
        "masking_rules": rules,
    }
    return json.dumps({"schema_version": 1, "connections": [connection]}, indent=2)


def gate(work: Work) -> str:
    """Return gate's YAML: every protected column name on its denylist."""
    pii = {
        "action": "redact",
        "wildcard_policy": "reject",
        "column_denylist": _names(work),
        "confidence_threshold": 0.8,
        "redaction": "[PII:{type}]",
        "include_summary": True,
        "hash_values": True,
        "hash_salt": "bench",
    }
    data = {"enabled": True, "pii": pii, "mcp": {"redact_tool_results": True}}
    return yaml.safe_dump({**data, "stats": {"enabled": True}}, sort_keys=False)


def januscope(work: Work) -> str:
    """Return JanuScope's YAML over ``mcp-sqlite``: a field rule per protected column."""
    names = _names(work)
    fields = [{"field": n if n in _LISTING_KEYS else f"**.{n}"} for n in names]
    policy = (
        "READ-ONLY SQLite. Use sqlite_get_catalog and sqlite_execute SELECT queries only.\n"
        f"Protected: {', '.join(names)}. Never return, reconstruct or transform protected "
        "values; aggregates that disclose none are fine.\n"
    )
    guard = {"tools": ["sqlite_execute"], "sqlArg": "sql", "readOnly": True, "mode": "allowlist"}
    data = {
        "target": {"command": "mcp-sqlite", "args": ["${SQLITE_DB_PATH}"]},
        "classification": "sensitive",
        "instructions": {"text": policy, "position": "prepend"},
        "sqlGuard": guard,
        "block": [f"{verb}_*" for verb in _WRITES],
        "redact": {"rules": fields, "replacement": "[REDACTED]", "applyTo": "text"},
        "audit": {"sink": "/audit/januscope-audit.jsonl", "logRawArgs": False},
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def veil(work: Work) -> str:
    """Return veil's Prisma schema: every protected column a ``/// @pii`` field."""
    models = []
    for table, cols in protected(work).items():
        fields = []
        for column, cls in cols.items():
            kind = "secret" if cls == "secret" else _kind(column) if cls == "identifier" else ""
            prisma = _prisma_type(work.schema[table][column])
            fields.append(f"  /// @pii {kind}".rstrip() + f"\n  {column} {prisma}")
        models.append(f"model {table} {{\n" + "\n".join(fields) + "\n}\n")
    return "\n".join(models)


def _kind(column: str) -> str:
    return next((kind for part, kind in _PII_KINDS if part in column.lower()), "")


def _prisma_type(declared: str) -> str:
    upper = declared.upper()
    return next((t for part, t in _PRISMA_TYPES if part in upper), "String")


def dbridge(work: Work) -> str:
    """Return dbridge-mcp's JSON: secrets and left-out columns hidden, the others masked."""
    by_cls: dict[bool, set[str]] = {True: set(), False: set()}
    for cols in protected(work).values():
        for column, cls in cols.items():
            by_cls[cls in _UNSAYABLE].add(column)
    data = {
        "maxRows": 1000,
        "statementTimeoutMs": 10000,
        "hiddenColumns": sorted(by_cls[True]),
        "maskedColumns": [{"column": c, "strategy": "full"} for c in sorted(by_cls[False])],
    }
    return json.dumps(data, indent=2)


def datacharter(work: Work) -> str:
    """Return DataCharter's charter: the set's file as one source, every protected column PII."""
    source = {
        "type": "sqlite",
        "path": f"/data/{work.path.name}",
        "tables": list(work.schema),
        "pii": {t: list(cols) for t, cols in protected(work).items()},
    }
    return yaml.safe_dump({"version": 1, "sources": {"bench": source}}, sort_keys=False)
