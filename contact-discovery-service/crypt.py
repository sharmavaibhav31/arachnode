from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_SALT = b"arachnode-url-encryption-salt-v1"


def _derive_key(passphrase: str) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=600_000)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def _get_fernet() -> Fernet:
    key = os.environ.get("ARACHNODE_ENCRYPTION_KEY")
    if not key:
        key = os.environ.get("HOSTNAME", "arachnode-default-dev-key")
    return Fernet(_derive_key(key))


def encrypt_url(url: str | None) -> str | None:
    if url is None:
        return None
    f = _get_fernet()
    return f.encrypt(url.encode()).decode()


def decrypt_url(encrypted: str | None) -> str | None:
    if encrypted is None:
        return None
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()
