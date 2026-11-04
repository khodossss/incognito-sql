"""Edges of the token layer: shortest TTL, dictionary connection, sealed blobs and key text."""

import base64
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from incognito_sql.core.tokens.crypto import NONCE_LEN, TAG_LEN, Cipher, load_key
from incognito_sql.core.tokens.db import BUSY_TIMEOUT_MS, connect
from incognito_sql.core.tokens.store import InvalidToken, TokenStore


def test_one_second_ttl_is_allowed(db_path: Path, cipher: Cipher, now: datetime) -> None:
    s = TokenStore(db_path, cipher, "inst:db", ttl_s=1)
    try:
        t = s.tokenize("Ivan", now)
        assert s.variants(t, now) == ["Ivan"]
        with pytest.raises(InvalidToken):
            s.variants(t, now + timedelta(seconds=1))
    finally:
        s.close()


def test_writes_outside_a_transaction_are_visible_at_once(db_path: Path) -> None:
    writer, reader = connect(db_path), connect(db_path)
    try:
        writer.execute("INSERT INTO value (canon_hash, sealed_canon) VALUES (x'01', x'02')")
        assert reader.execute("SELECT count(*) FROM value").fetchone()[0] == 1
    finally:
        writer.close()
        reader.close()


def test_connection_waits_for_a_busy_dictionary(db_path: Path) -> None:
    con = connect(db_path)
    try:
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
    finally:
        con.close()


def test_cipher_seals_empty_text() -> None:
    c = Cipher(os.urandom(32))
    sealed = c.seal("")
    assert len(sealed) == NONCE_LEN + TAG_LEN
    assert c.open(sealed) == ""


@pytest.mark.parametrize("length", [0, 7, NONCE_LEN, NONCE_LEN + TAG_LEN - 1])
def test_cipher_rejects_truncated_blobs(length: int) -> None:
    with pytest.raises(InvalidTag):
        Cipher(os.urandom(32)).open(b"x" * length)


@pytest.mark.parametrize("junk", ["!", " ", "\n", "$$"])
def test_load_key_rejects_key_text_with_stray_characters(
    monkeypatch: pytest.MonkeyPatch, junk: str
) -> None:
    text = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("INCOGNITO_SQL_KEY", text[:8] + junk + text[8:])
    with pytest.raises(ValueError, match="INCOGNITO_SQL_KEY"):
        load_key()
