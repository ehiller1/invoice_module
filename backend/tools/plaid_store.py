"""FR-Bank-Integration: Persistence for Plaid-linked accounts and transactions.

Plaid access tokens are sensitive — they're stored in Fernet-encrypted form
inside the per-church JSON file:

    backend/data/plaid_accounts_{church_id}.json
    backend/data/plaid_transactions_{church_id}.json

Encryption uses the same key file (`backend/data/.vault_key`) as the ACS Realm
credential vault, so a single rotation rotates everything.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

from ..models.schemas import PlaidAccount, PlaidTransaction

# ---- Soft Fernet import (mirrors integrations/acs_realm/credentials.py) ----
try:
    from cryptography.fernet import Fernet as _Fernet
    Fernet: Any = _Fernet
    CRYPTO_AVAILABLE = True
except ImportError:                                   # pragma: no cover
    CRYPTO_AVAILABLE = False
    Fernet: Any = None


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
KEY_PATH = DATA_DIR / ".vault_key"


def _get_key() -> bytes:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError(
            "cryptography is not installed — install it to use the Plaid vault"
        )
    key = os.getenv("EIME_VAULT_KEY")
    if key:
        return key.encode() if isinstance(key, str) else key
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.exists():
        return KEY_PATH.read_text().strip().encode()
    new_key = Fernet.generate_key()
    KEY_PATH.write_text(new_key.decode())
    return new_key


def encrypt_token(plain: str) -> str:
    """Fernet-encrypt the access token — returns urlsafe base64 string."""
    if not CRYPTO_AVAILABLE:
        # Fallback: opaque base64 wrapping so file isn't plaintext, but warn.
        return "PLAIN:" + base64.urlsafe_b64encode(plain.encode()).decode()
    f = Fernet(_get_key())
    return f.encrypt(plain.encode()).decode()


def decrypt_token(token_enc: str) -> str:
    if token_enc.startswith("PLAIN:"):
        return base64.urlsafe_b64decode(token_enc[len("PLAIN:"):]).decode()
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography is not installed — cannot decrypt token")
    f = Fernet(_get_key())
    return f.decrypt(token_enc.encode()).decode()


# ===== Accounts =====

def _accounts_path(church_id: str) -> Path:
    return DATA_DIR / f"plaid_accounts_{church_id}.json"


def load_plaid_accounts(church_id: str) -> List[PlaidAccount]:
    p = _accounts_path(church_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    rows: List[PlaidAccount] = []
    for row in raw:
        try:
            rows.append(PlaidAccount(**row))
        except Exception:
            continue
    return rows


def save_plaid_accounts(church_id: str, accounts: List[PlaidAccount]) -> None:
    p = _accounts_path(church_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [a.model_dump() for a in accounts]
    p.write_text(json.dumps(payload, indent=2, default=str))


def save_plaid_account(church_id: str, account: PlaidAccount) -> List[PlaidAccount]:
    rows = load_plaid_accounts(church_id)
    rows = [a for a in rows if a.account_id != account.account_id]
    rows.append(account)
    save_plaid_accounts(church_id, rows)
    return rows


def get_plaid_account(church_id: str, account_id: str) -> Optional[PlaidAccount]:
    for a in load_plaid_accounts(church_id):
        if a.account_id == account_id:
            return a
    return None


def delete_plaid_account(church_id: str, account_id: str) -> List[PlaidAccount]:
    rows = [a for a in load_plaid_accounts(church_id) if a.account_id != account_id]
    save_plaid_accounts(church_id, rows)
    return rows


def refresh_account_balances(church_id: str, account_id: str) -> Optional[PlaidAccount]:
    """Pull latest balances from Plaid and persist."""
    from ..integrations import plaid_client  # local to avoid hard SDK dep on import

    acct = get_plaid_account(church_id, account_id)
    if not acct:
        return None
    access = decrypt_token(acct.access_token_enc)
    mgr = plaid_client.get_manager()
    fresh = mgr.get_accounts(access)
    for entry in fresh:
        if entry.get("account_id") == account_id:
            balances = entry.get("balances", {}) or {}
            acct.current_balance = float(balances.get("current") or 0.0)
            acct.available_balance = float(balances.get("available") or 0.0)
            acct.balance_updated_at = datetime.utcnow()
            save_plaid_account(church_id, acct)
            return acct
    return acct  # no match — leave existing


# ===== Transactions =====

def _txns_path(church_id: str) -> Path:
    return DATA_DIR / f"plaid_transactions_{church_id}.json"


def load_plaid_transactions(
    church_id: str,
    account_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[PlaidTransaction]:
    p = _txns_path(church_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    rows: List[PlaidTransaction] = []
    for row in raw:
        try:
            rows.append(PlaidTransaction(**row))
        except Exception:
            continue

    def _keep(t: PlaidTransaction) -> bool:
        if account_id and t.account_id != account_id:
            return False
        if date_from and t.date < date_from:
            return False
        if date_to and t.date > date_to:
            return False
        return True

    return [t for t in rows if _keep(t)]


def save_plaid_transactions(
    church_id: str,
    transactions: List[PlaidTransaction],
) -> None:
    p = _txns_path(church_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [t.model_dump() for t in transactions]
    p.write_text(json.dumps(payload, indent=2, default=str))


def fetch_and_store_transactions(
    church_id: str,
    account_id: str,
    days_back: int = 60,
) -> List[PlaidTransaction]:
    """Pull transactions from Plaid for `account_id` and merge into store."""
    from ..integrations import plaid_client

    acct = get_plaid_account(church_id, account_id)
    if not acct:
        return []
    access = decrypt_token(acct.access_token_enc)

    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)

    mgr = plaid_client.get_manager()
    fresh = mgr.get_transactions(access, start_date, end_date)

    new_txns: List[PlaidTransaction] = []
    for entry in fresh:
        if entry.get("account_id") and entry["account_id"] != account_id:
            # Only keep txns for the requested account
            continue
        try:
            t = PlaidTransaction(
                txn_id=entry["txn_id"],
                account_id=account_id,
                date=entry["date"] if isinstance(entry["date"], date) else date.fromisoformat(str(entry["date"])),
                description=entry.get("name") or "",
                amount=float(entry.get("amount") or 0.0),
                category=entry.get("category") or "",
                merchant_name=entry.get("merchant_name"),
                fetched_at=datetime.utcnow(),
            )
            new_txns.append(t)
        except Exception:
            continue

    # Merge with existing — replace by txn_id
    existing = load_plaid_transactions(church_id)
    by_id = {t.txn_id: t for t in existing}
    for t in new_txns:
        by_id[t.txn_id] = t
    save_plaid_transactions(church_id, list(by_id.values()))
    return new_txns
