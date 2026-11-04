"""safedb-mcp on a set's SQLite file, configured from our marking.

The configuration is written the way ``bench/adapters/config/safedb_mcp.sqlite.yaml`` is:
every table allowlisted, a mask on every column that is not shown (identifiers hashed,
emails and phones partly shown, the rest redacted). safedb-mcp matches table and column
names as the query spells them, case-sensitively, while SQLite does not; a set's queries
spell names in any case, so every name is listed as stored, in lower and in upper case.
"""

from pathlib import Path

import yaml

from bench.adapters import launch, safedb_mcp
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database
from bench.external.marking import SHOWN
from bench.external.volume import volume
from bench.external.work import Work

_MASK_BY_NAME = (
    ("email", "email"),
    ("phone", "partial"),
    ("mobile", "partial"),
    ("cell", "partial"),
)


def spellings(name: str) -> list[str]:
    """Return a name as stored, in lower and in upper case, each once."""
    return list(dict.fromkeys((name, name.lower(), name.upper())))


def config(work: Work) -> str:
    """Return the safedb-mcp configuration of ``work``."""
    m = work.marking
    masks = {
        f"{t_as}.{c_as}": _mask(c, m.cls(t, c))
        for t, cols in work.schema.items()
        for c in cols
        if m.cls(t, c) not in SHOWN
        for t_as in spellings(t)
        for c_as in spellings(c)
    }
    tables = [spelled for t in work.schema for spelled in spellings(t)]
    safety = {"default_limit": 100, "max_limit": 1000, "statement_timeout_ms": 5000}
    data = {
        "database": {"type": "sqlite", "path": f"/data/{work.path.name}"},
        "safety": {**safety, "allow_explain": True},
        "access": {"schemas": {"main": {"allow_tables": tables, "column_masks": masks}}},
        "audit": {"path": "/audit/safedb-audit.jsonl"},
        "masking": {"hash_salt": "bench"},
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _mask(column: str, cls: str) -> str:
    if cls != "identifier":
        return "redact"  # free text, secrets, columns left out
    return next((mask for part, mask in _MASK_BY_NAME if part in column.lower()), "hash")


def open_safedb(work: Work, db: Database, workdir: Path) -> StdioAdapter:
    """Start safedb-mcp in a container; the file reaches it on a docker volume."""
    image = launch.ensure_image(safedb_mcp.IMAGE, repo=safedb_mcp.REPO, sha=safedb_mcp.SHA)
    folder = workdir / "config"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "safedb.yaml").write_text(config(work), encoding="utf-8")
    mounts: dict[Path | str, str] = {
        folder: "/config:ro",
        workdir: "/audit",
        volume(work.path): "/data:ro",
    }
    params = launch.container(image, db, {}, mounts, ["--config", "/config/safedb.yaml"])
    calls = (lambda sql: {"query": sql}, safedb_mcp.parse)
    audit = workdir / "safedb-audit.jsonl"
    return StdioAdapter(safedb_mcp.INFO, "sqlite", params, calls, workdir=workdir, audit=audit)
