import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import InvalidToken, TokenStore


def test_same_value_any_column_same_token(store: TokenStore, now: datetime) -> None:
    assert store.tokenize("Ivan Petrov", now) == store.tokenize(" ivan  petrov", now)


def test_variants_keep_raw_forms(store: TokenStore, now: datetime) -> None:
    t = store.tokenize("Ivan Petrov", now)
    store.tokenize("ivan petrov ", now)
    store.tokenize("ivan petrov ", now)
    assert sorted(store.variants(t, now)) == ["Ivan Petrov", "ivan petrov "]


def test_ttl_rotates_token_but_reveal_keeps_old(store: TokenStore, now: datetime) -> None:
    old = store.tokenize("Ivan", now)
    later = now + timedelta(hours=25)
    new = store.tokenize("Ivan", later)
    assert new != old
    with pytest.raises(InvalidToken):
        store.variants(old, later)
    assert store.reveal(old) == "Ivan"
    assert store.variants(new, later) == ["Ivan"]


def test_forever_ttl_never_rotates(tmp_path: Path, cipher: Cipher, now: datetime) -> None:
    s = TokenStore(tmp_path / "d.db", cipher, "inst:db", ttl_s=None)
    assert s.tokenize("Ivan", now) == s.tokenize("Ivan", now + timedelta(days=400))
    s.close()


def test_foreign_domain_and_forged_token_same_error(
    store: TokenStore, other_domain_store: TokenStore, now: datetime
) -> None:
    t = other_domain_store.tokenize("Ivan", now)
    for bad in (t, "tk_" + "a" * 16, "tk_short"):
        with pytest.raises(InvalidToken) as info:
            store.variants(bad, now)
        assert "Ivan" not in str(info.value)
        assert bad not in str(info.value)
        with pytest.raises(InvalidToken):
            store.reveal(bad)


def test_same_value_different_domain_different_token(
    store: TokenStore, other_domain_store: TokenStore, now: datetime
) -> None:
    assert store.tokenize("Ivan", now) != other_domain_store.tokenize("Ivan", now)


def test_numeric_identifier_tokenized_by_string_canon(store: TokenStore, now: datetime) -> None:
    assert store.tokenize(972501234567, now) == store.tokenize("972501234567", now)


def test_variants_for_literal(store: TokenStore, now: datetime) -> None:
    assert store.variants_for_literal("Zzunknown") == ["Zzunknown"]
    store.tokenize("Ivan", now)
    store.tokenize("IVAN", now)
    out = store.variants_for_literal(" ivan")
    assert out[0] == " ivan"
    assert sorted(out[1:]) == ["IVAN", "Ivan"]
    assert store.variants_for_literal("Ivan") == ["Ivan", "IVAN"]


def test_literal_lookup_creates_nothing(store: TokenStore, db_path: Path) -> None:
    store.variants_for_literal("Zzghost")
    con = sqlite3.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM value").fetchone() == (0,)
    finally:
        con.close()


def test_naive_datetime_rejected(store: TokenStore) -> None:
    with pytest.raises(ValueError, match="timezone"):
        store.tokenize("Ivan", datetime(2026, 1, 1))  # noqa: DTZ001


def test_token_collision_retried(
    store: TokenStore, now: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = store.tokenize("Ivan", now)
    seq = iter([first, "tk_" + "b" * 16])
    monkeypatch.setattr("incognito_sql.core.tokens.store.new_token", lambda: next(seq))
    assert store.tokenize("Petr", now) == "tk_" + "b" * 16


def test_no_plaintext_on_disk(store: TokenStore, now: datetime, tmp_path: Path) -> None:
    store.tokenize("Zzcanary Qqperson", now)
    blob = b"".join(p.read_bytes() for p in tmp_path.glob("d.db*"))
    assert b"Zzcanary" not in blob
    assert b"zzcanary" not in blob


def test_second_connection_sees_same_token(
    db_path: Path, cipher: Cipher, store: TokenStore, now: datetime
) -> None:
    other = TokenStore(db_path, cipher, "inst:db", ttl_s=24 * 3600)
    assert store.tokenize("Ivan", now) == other.tokenize("ivan", now)
    other.close()


def test_variants_are_scoped_to_domain(
    store: TokenStore, other_domain_store: TokenStore, now: datetime
) -> None:
    ta = store.tokenize("Ivan", now)
    tb = other_domain_store.tokenize("IVAN", now)
    assert store.reveal(ta) == "Ivan"
    assert other_domain_store.reveal(tb) == "IVAN"
    assert store.variants(ta, now) == ["Ivan"]
    assert store.variants_for_literal("ivan") == ["ivan", "Ivan"]
    assert other_domain_store.variants_for_literal("ivan") == ["ivan", "IVAN"]


def test_threads_can_use_the_store(store: TokenStore, now: datetime) -> None:
    out: list[object] = []

    def work() -> None:
        t = store.tokenize("Ivan", now)
        out.append((t, store.variants(t, now)))

    th = threading.Thread(target=work)
    th.start()
    th.join()
    assert out == [(store.tokenize("Ivan", now), ["Ivan"])]


def test_concurrent_tokenize_gives_one_token(db_path: Path, cipher: Cipher, now: datetime) -> None:
    stores = [TokenStore(db_path, cipher, "inst:db", ttl_s=3600) for _ in range(4)]
    out: list[str] = []
    errors: list[Exception] = []

    def work(s: TokenStore) -> None:
        try:
            out.append(s.tokenize("Ivan", now))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(s,)) for s in stores]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    for s in stores:
        s.close()
    assert not errors
    assert len(out) == 4
    assert len(set(out)) == 1


def test_ttl_boundary(store: TokenStore, now: datetime) -> None:
    ttl = 24 * 3600
    t = store.tokenize("Ivan", now)
    just_before = now + timedelta(seconds=ttl - 1)
    assert store.tokenize("Ivan", just_before) == t
    assert store.variants(t, just_before) == ["Ivan"]
    edge = now + timedelta(seconds=ttl)
    with pytest.raises(InvalidToken):
        store.variants(t, edge)
    assert store.tokenize("Ivan", edge) != t


@pytest.mark.parametrize("ttl", [0, -5])
def test_non_positive_ttl_rejected(db_path: Path, cipher: Cipher, ttl: int) -> None:
    with pytest.raises(ValueError, match="ttl_s"):
        TokenStore(db_path, cipher, "inst:db", ttl_s=ttl)


def test_failed_commit_rolls_back() -> None:
    class Failing:
        in_transaction = True
        calls: list[str] = []  # noqa: RUF012

        def execute(self, sql: str) -> None:
            self.calls.append(sql)
            if sql == "COMMIT":
                msg = "boom"
                raise sqlite3.OperationalError(msg)

    from incognito_sql.core.tokens.db import Tx  # noqa: PLC0415

    con = Failing()
    with pytest.raises(sqlite3.OperationalError, match="boom"), Tx(con):  # type: ignore[arg-type]
        pass
    assert con.calls == ["BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"]
