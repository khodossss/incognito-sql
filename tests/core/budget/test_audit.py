import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from incognito_sql.core.audit import AuditLog, tokenize_sql_for_audit
from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import enforce
from incognito_sql.core.sql.resolve import qualify_tree
from incognito_sql.core.tokens.store import TokenStore

from .conftest import CATALOG, DECL

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _tokenized(store: TokenStore, sql: str, dialect: str = "postgres") -> str:
    tree = qualify_tree(parse(sql, dialect, Limits()), CATALOG, dialect)
    result = enforce(tree, CATALOG, DECL)
    return tokenize_sql_for_audit(tree, result, store, NOW, dialect=dialect)


@pytest.mark.parametrize("dialect", ["postgres", "sqlite"])
def test_identifier_literal_replaced_by_token(store: TokenStore, dialect: str) -> None:
    out = _tokenized(
        store, "SELECT id FROM people WHERE full_name = 'Ivan Petrov' AND id = 7", dialect
    )
    assert "Ivan" not in out
    assert store.tokenize("Ivan Petrov", NOW) in out
    assert "7" in out


def test_tree_not_modified_and_tokens_stay(store: TokenStore) -> None:
    token = store.tokenize("Ivan Petrov", NOW)
    sql = "SELECT id FROM people WHERE full_name IN ('%s', 'Zqother')" % token  # noqa: UP031, S608
    tree = qualify_tree(parse(sql, "postgres", Limits()), CATALOG, "postgres")
    before = tree.sql()
    out = tokenize_sql_for_audit(tree, enforce(tree, CATALOG, DECL), store, NOW, dialect="postgres")
    assert tree.sql() == before
    assert token in out
    assert "Zqother" not in out


def test_record_writes_one_jsonl_line_without_values(tmp_path: Path, store: TokenStore) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    sql = _tokenized(store, "SELECT id FROM people WHERE full_name = 'Ivan Petrov'")
    log.record(outcome="ok", reason=None, tables=["people"], row_count=1, ms=3, sql_tokenized=sql)
    log.record(
        outcome="rejected",
        reason=Reason.HIDDEN_COLUMN,
        tables=[],
        row_count=0,
        ms=1,
        sql_tokenized=None,
    )
    text = path.read_text("utf-8")
    assert "Ivan" not in text
    ok, rejected = (json.loads(line) for line in text.splitlines())
    assert ok["reason"] is None
    assert ok["sql_tokenized"] == sql
    assert ok["tables"] == ["people"]
    assert (ok["row_count"], ok["ms"], ok["outcome"]) == (1, 3, "ok")
    assert rejected["reason"] == "hidden_column"
    assert rejected["sql_tokenized"] is None
    assert ok["columns"] == rejected["columns"] == []
    assert datetime.fromisoformat(ok["ts"]).tzinfo is not None


def test_appends_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    for _ in range(2):
        AuditLog(path).record(
            outcome="ok", reason=None, tables=[], row_count=0, ms=0, sql_tokenized="SELECT 1"
        )
    assert len(path.read_text("utf-8").splitlines()) == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    AuditLog(path)
    assert path.stat().st_mode & 0o777 == 0o600


def test_tokenized_sql_stays_in_the_query_dialect(store: TokenStore) -> None:
    out = _tokenized(store, "SELECT TOP 1 id FROM people WHERE full_name = 'Ivan Petrov'", "tsql")
    assert "TOP 1" in out
    assert "LIMIT" not in out


def test_comments_never_reach_the_tokenized_sql(store: TokenStore) -> None:
    sql = "SELECT id /* Ivan Petrov */ FROM people WHERE full_name = 'x' -- Zqcanary"
    out = _tokenized(store, sql)
    assert "Ivan" not in out
    assert "Zqcanary" not in out


def test_non_ascii_stays_readable_in_the_line(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    sql = "SELECT id FROM заказы WHERE город = 'Хайфа'"
    AuditLog(path).record(
        outcome="ok", reason=None, tables=["заказы"], row_count=0, ms=0, sql_tokenized=sql
    )
    text = path.read_text("utf-8")
    assert '"tables": ["заказы"]' in text
    assert json.loads(text)["sql_tokenized"] == sql
