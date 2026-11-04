import base64
import os
from collections.abc import Iterator

import keyring
import keyring.errors
import pytest
from cryptography.exceptions import InvalidTag
from keyring.backend import KeyringBackend

from incognito_sql.core.tokens.canon import canonical
from incognito_sql.core.tokens.crypto import Cipher, load_key
from incognito_sql.core.tokens.format import TOKEN_RE, new_token


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> Iterator[MemoryKeyring]:
    monkeypatch.delenv("INCOGNITO_SQL_KEY", raising=False)
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def test_canonical_folds_case_and_space() -> None:
    assert canonical("  Ivan   PETROV ") == canonical("ivan petrov") == "ivan petrov"


def test_canonical_number_and_string_match() -> None:
    assert canonical(972501234567) == canonical("972501234567")


def test_token_shape() -> None:
    assert TOKEN_RE.match(new_token())


def test_tokens_differ() -> None:
    assert new_token() != new_token()


def test_cipher_roundtrip_and_tamper() -> None:
    c = Cipher(os.urandom(32))
    sealed = c.seal("Ivan")
    assert c.open(sealed) == "Ivan"
    with pytest.raises(InvalidTag):
        c.open(sealed[:-1] + bytes([sealed[-1] ^ 1]))


def test_cipher_open_too_short() -> None:
    with pytest.raises(InvalidTag):
        Cipher(os.urandom(32)).open(b"x" * 27)


def test_load_key_bad_keyring_value_names_keyring(fake_keyring: MemoryKeyring) -> None:
    fake_keyring.set_password("incognito-sql", "value-key", "AAAA")
    with pytest.raises(ValueError, match="keyring value"):
        load_key()


class BrokenKeyring(MemoryKeyring):
    def get_password(self, service: str, username: str) -> str | None:  # noqa: ARG002
        raise keyring.errors.NoKeyringError


@pytest.mark.usefixtures("fake_keyring")
def test_load_key_no_keyring_backend() -> None:
    keyring.set_keyring(BrokenKeyring())
    with pytest.raises(RuntimeError, match="INCOGNITO_SQL_KEY"):
        load_key()


class _Raising(MemoryKeyring):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc = exc

    def get_password(self, service: str, username: str) -> str | None:  # noqa: ARG002
        raise self.exc


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("backend failed near Zq7SECRETpw"),
        UnicodeDecodeError("utf-8", b"Zq7SECRETpw", 0, 1, "bad"),
        OSError("Zq7SECRETpw"),
    ],
)
@pytest.mark.usefixtures("fake_keyring")
def test_a_backend_s_own_text_is_never_repeated(exc: Exception) -> None:
    keyring.set_keyring(_Raising(exc))
    with pytest.raises(RuntimeError) as raised:
        load_key()
    assert "Zq7SECRETpw" not in str(raised.value)
    assert "INCOGNITO_SQL_KEY" in str(raised.value)
    assert raised.value.__cause__ is None


def test_cipher_nonce_random() -> None:
    c = Cipher(os.urandom(32))
    assert c.seal("Ivan") != c.seal("Ivan")


def test_cipher_rejects_bad_key_length() -> None:
    with pytest.raises(ValueError, match="32"):
        Cipher(b"short")


def test_mac_deterministic_and_distinct() -> None:
    key = os.urandom(32)
    c = Cipher(key)
    assert c.mac("ivan") == c.mac("ivan")
    assert len(c.mac("ivan")) == 32
    assert c.mac("ivan") != c.mac("petrov")
    assert Cipher(os.urandom(32)).mac("ivan") != c.mac("ivan")


def test_load_key_prefers_env(monkeypatch: pytest.MonkeyPatch, fake_keyring: MemoryKeyring) -> None:
    raw = os.urandom(32)
    monkeypatch.setenv("INCOGNITO_SQL_KEY", base64.b64encode(raw).decode())
    assert load_key() == raw
    assert not fake_keyring.store


def test_load_key_malformed_env(
    monkeypatch: pytest.MonkeyPatch, fake_keyring: MemoryKeyring
) -> None:
    monkeypatch.setenv("INCOGNITO_SQL_KEY", "not base64!!")
    with pytest.raises(ValueError, match="INCOGNITO_SQL_KEY"):
        load_key()
    monkeypatch.setenv("INCOGNITO_SQL_KEY", base64.b64encode(b"short").decode())
    with pytest.raises(ValueError, match="INCOGNITO_SQL_KEY"):
        load_key()
    assert not fake_keyring.store


def test_load_key_reads_keyring(fake_keyring: MemoryKeyring) -> None:
    raw = os.urandom(32)
    fake_keyring.set_password("incognito-sql", "value-key", base64.b64encode(raw).decode())
    assert load_key() == raw


def test_load_key_generates_and_stores(fake_keyring: MemoryKeyring) -> None:
    first = load_key()
    assert len(first) == 32
    assert (
        fake_keyring.get_password("incognito-sql", "value-key") == base64.b64encode(first).decode()
    )
    assert load_key() == first
