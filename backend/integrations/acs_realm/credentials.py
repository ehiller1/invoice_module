"""Encrypted credential vault for ACS Realm logins (FR-06.5)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

# Cryptography is a soft dep — the module imports lazily so unit tests that
# don't touch the vault still pass even when cryptography is absent.
try:
    from cryptography.fernet import Fernet as _Fernet
    Fernet: Any = _Fernet
    CRYPTO_AVAILABLE = True
except ImportError:                                   # pragma: no cover
    CRYPTO_AVAILABLE = False
    Fernet: Any = None

VAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "acs_credentials.enc"
KEY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / ".vault_key"


def _ensure_data_dir() -> None:
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)


def _get_key() -> bytes:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError(
            "cryptography is not installed — install Fernet support to use the ACS vault"
        )
    key = os.getenv("EIME_VAULT_KEY")
    if key:
        return key.encode() if isinstance(key, str) else key
    _ensure_data_dir()
    if KEY_PATH.exists():
        return KEY_PATH.read_text().strip().encode()
    new_key = Fernet.generate_key()  # bytes
    KEY_PATH.write_text(new_key.decode())
    return new_key


def store(church_id: str, username: str, password: str, base_url: str) -> None:
    """Encrypt and persist credentials for `church_id`."""
    _ensure_data_dir()
    f = Fernet(_get_key())
    data: dict = {}
    if VAULT_PATH.exists():
        try:
            data = json.loads(f.decrypt(VAULT_PATH.read_bytes()).decode())
        except Exception:
            data = {}
    data[church_id] = {
        "username": username,
        "password": password,
        "base_url": base_url,
    }
    encrypted = f.encrypt(json.dumps(data).encode())
    VAULT_PATH.write_bytes(encrypted)


def retrieve(church_id: str) -> Optional[dict]:
    """Return decrypted credentials for `church_id`, or None if unset."""
    if not VAULT_PATH.exists():
        return None
    try:
        f = Fernet(_get_key())
        data = json.loads(f.decrypt(VAULT_PATH.read_bytes()).decode())
    except Exception:
        return None
    return data.get(church_id)
