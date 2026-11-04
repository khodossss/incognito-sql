"""Value encryption (AES-GCM), canonical-form MAC and key loading."""

import base64
import binascii
import hashlib
import hmac
import os
import secrets

import keyring
import keyring.errors
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_LEN = 32
NONCE_LEN = 12
TAG_LEN = 16
ENV_KEY = "INCOGNITO_SQL_KEY"
KEYRING_USER = "value-key"
_MAC_INFO = b"incognito-sql canon mac"


class Cipher:
    """Encrypts values with AES-GCM and derives lookup MACs from the same key."""

    def __init__(self, key: bytes) -> None:
        """Create a cipher; the key must be exactly 32 bytes."""
        if len(key) != KEY_LEN:
            msg = f"key must be {KEY_LEN} bytes"
            raise ValueError(msg)
        self._aead = AESGCM(key)
        self._mac_key = HKDF(
            algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=_MAC_INFO
        ).derive(key)

    def seal(self, plain: str) -> bytes:
        """Encrypt text; the 12-byte random nonce is prepended to the result."""
        nonce = os.urandom(NONCE_LEN)
        return nonce + self._aead.encrypt(nonce, plain.encode(), None)

    def open(self, sealed: bytes) -> str:
        """Decrypt output of ``seal``; raises ``InvalidTag`` if it was altered."""
        if len(sealed) < NONCE_LEN + TAG_LEN:
            raise InvalidTag
        return self._aead.decrypt(sealed[:NONCE_LEN], sealed[NONCE_LEN:], None).decode()

    def mac(self, text: str) -> bytes:
        """Return a keyed, deterministic digest of text (for lookups without decrypting)."""
        return hmac.new(self._mac_key, text.encode(), hashlib.sha256).digest()


def load_key(service: str = "incognito-sql") -> bytes:
    """Return the 32-byte key: from the environment, else the OS keyring, else new."""
    env = os.environ.get(ENV_KEY)
    if env is not None:
        return _decode(env, ENV_KEY)
    try:
        stored = keyring.get_password(service, KEYRING_USER)
        if stored is None:
            key = secrets.token_bytes(KEY_LEN)
            keyring.set_password(service, KEYRING_USER, base64.b64encode(key).decode("ascii"))
            return key
    except Exception:  # noqa: BLE001 -- a backend's own text may carry anything: never repeat it
        msg = f"no usable OS keyring; set {ENV_KEY} to base64 of {KEY_LEN} random bytes"
        raise RuntimeError(msg) from None
    return _decode(stored, "keyring value")


def _decode(text: str, source: str) -> bytes:
    try:
        key = base64.b64decode(text, validate=True)
    except binascii.Error as exc:
        msg = f"{source} must be base64 of {KEY_LEN} bytes"
        raise ValueError(msg) from exc
    if len(key) != KEY_LEN:
        msg = f"{source} must be base64 of {KEY_LEN} bytes"
        raise ValueError(msg)
    return key
