"""FR-05.2: cryptographically-random one-time approval tokens.

Tokens are 32 random bytes, URL-safe encoded. State is persisted to
`backend/data/approval_tokens.json` as a flat dict keyed by token string. Each
entry tracks expiry and the single-use flag.

This is intentionally a simple, file-backed store — sufficient for the EIME
single-tenant deployment model. A production multi-tenant deployment should
move to Redis/Postgres.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

TOKEN_STORE = Path(__file__).resolve().parent.parent.parent / "data" / "approval_tokens.json"
_LOCK = threading.Lock()


def _read_store() -> Dict[str, Dict[str, Any]]:
    if not TOKEN_STORE.exists():
        return {}
    try:
        return json.loads(TOKEN_STORE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_store(data: Dict[str, Dict[str, Any]]) -> None:
    TOKEN_STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_STORE.with_suffix(TOKEN_STORE.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, TOKEN_STORE)


def mint(action: str, decision_context: Dict[str, Any], role: str,
         ttl_seconds: int = 48 * 3600) -> str:
    """Generate a single-use token and persist it.

    Returns the token string. Caller embeds it in the approval URL.
    """
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + ttl_seconds
    with _LOCK:
        store = _read_store()
        store[token] = {
            "action": action,
            "context": decision_context,
            "role": role,
            "expires_at": expires_at,
            "used": False,
            "created_at": time.time(),
        }
        _write_store(store)
    return token


def consume(token: str) -> Optional[Dict[str, Any]]:
    """Atomically validate + mark token as used.

    Returns the original claims dict on success, or None if the token is
    unknown, expired, or already consumed.
    """
    if not token:
        return None
    with _LOCK:
        store = _read_store()
        entry = store.get(token)
        if not entry:
            return None
        if entry.get("used"):
            return None
        if float(entry.get("expires_at", 0)) < time.time():
            return None
        entry["used"] = True
        entry["consumed_at"] = time.time()
        store[token] = entry
        _write_store(store)
        # Return a copy of the claims (without the used flag for clarity).
        return {
            "action": entry["action"],
            "context": entry["context"],
            "role": entry["role"],
            "expires_at": entry["expires_at"],
        }


def peek(token: str) -> Optional[Dict[str, Any]]:
    """Read token claims WITHOUT consuming. For diagnostics only."""
    if not token:
        return None
    store = _read_store()
    return store.get(token)
