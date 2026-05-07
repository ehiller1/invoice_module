"""FR-Bank-Integration: Plaid API client wrapper.

This module wraps the `plaid-python` SDK so the rest of the codebase can call
into a small surface (create-link-token, exchange-public-token, get-accounts,
get-transactions) without importing Plaid SDK types directly.

The SDK is a soft dependency — when the package isn't available the
PlaidManager raises a clear runtime error. Tests must monkeypatch
`PlaidManager` (or use `MockPlaidManager`) to avoid hitting the real API.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

# Soft import — kept lazy so unit tests pass without the SDK.
try:
    import plaid  # type: ignore
    from plaid import ApiClient, Configuration  # type: ignore
    from plaid.api import plaid_api  # type: ignore
    from plaid.model.country_code import CountryCode  # type: ignore
    from plaid.model.language_code import LanguageCode  # type: ignore
    from plaid.model.products import Products  # type: ignore
    from plaid.model.link_token_create_request import LinkTokenCreateRequest  # type: ignore
    from plaid.model.link_token_create_request_user import (  # type: ignore
        LinkTokenCreateRequestUser as LinkTokenUser,
    )
    from plaid.model.item_public_token_exchange_request import (  # type: ignore
        ItemPublicTokenExchangeRequest,
    )
    from plaid.model.accounts_get_request import AccountsGetRequest  # type: ignore
    from plaid.model.transactions_get_request import TransactionsGetRequest  # type: ignore
    from plaid.model.transactions_get_request_options import (  # type: ignore
        TransactionsGetRequestOptions,
    )
    PLAID_AVAILABLE = True
except ImportError:                                 # pragma: no cover
    PLAID_AVAILABLE = False
    plaid = None  # type: ignore
    ApiClient = Configuration = None  # type: ignore
    plaid_api = None  # type: ignore
    CountryCode = LanguageCode = Products = None  # type: ignore
    LinkTokenCreateRequest = LinkTokenUser = None  # type: ignore
    ItemPublicTokenExchangeRequest = None  # type: ignore
    AccountsGetRequest = None  # type: ignore
    TransactionsGetRequest = TransactionsGetRequestOptions = None  # type: ignore


def _require_sdk() -> None:
    if not PLAID_AVAILABLE:
        raise RuntimeError(
            "plaid-python is not installed — install plaid-python>=15.0.0 to use Plaid"
        )


class PlaidManager:
    """Thin wrapper around `plaid_api.PlaidApi`."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        secret: Optional[str] = None,
        env: str = "sandbox",
    ) -> None:
        _require_sdk()
        client_id = client_id or os.environ.get("PLAID_CLIENT_ID")
        secret = secret or os.environ.get("PLAID_SECRET")
        if not client_id or not secret:
            raise RuntimeError(
                "Plaid credentials missing — set PLAID_CLIENT_ID and PLAID_SECRET"
            )
        host = getattr(plaid.Environment, env.upper(), plaid.Environment.Sandbox)
        self.config = Configuration(
            host=host,
            api_key={"clientId": client_id, "secret": secret},
        )
        self.client = ApiClient(self.config)
        self.api = plaid_api.PlaidApi(self.client)

    def create_link_token(
        self,
        user_id: str,
        church_name: str,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate Plaid Link token for the UI modal."""
        _require_sdk()
        kwargs = dict(
            user=LinkTokenUser(client_user_id=user_id),
            client_name=f"{church_name} - EIME",
            language=LanguageCode("en"),
            products=[Products("auth"), Products("transactions")],
            country_codes=[CountryCode("US")],
        )
        # webhook + redirect optional
        webhook = os.environ.get("PLAID_WEBHOOK_URL")
        if webhook:
            kwargs["webhook"] = webhook
        if redirect_uri:
            kwargs["redirect_uri"] = redirect_uri
        request = LinkTokenCreateRequest(**kwargs)
        response = self.api.link_token_create(request)
        return {
            "link_token": response.link_token,
            "expiration": str(response.expiration),
        }

    def exchange_public_token(self, public_token: str) -> str:
        _require_sdk()
        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = self.api.item_public_token_exchange(request)
        return response.access_token

    def get_accounts(self, access_token: str) -> List[Dict[str, Any]]:
        _require_sdk()
        request = AccountsGetRequest(access_token=access_token)
        response = self.api.accounts_get(request)
        out: List[Dict[str, Any]] = []
        for acct in response.accounts:
            out.append({
                "account_id": acct.account_id,
                "name": acct.name,
                "subtype": str(acct.subtype) if acct.subtype else "",
                "type": str(acct.type) if acct.type else "",
                "mask": acct.mask or "",
                "balances": {
                    "current": float(acct.balances.current) if acct.balances.current is not None else 0.0,
                    "available": float(acct.balances.available) if acct.balances.available is not None else 0.0,
                    "limit": float(acct.balances.limit) if acct.balances.limit is not None else None,
                },
            })
        return out

    def get_transactions(
        self,
        access_token: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        _require_sdk()
        request = TransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            options=TransactionsGetRequestOptions(
                include_personal_finance_category=True
            ),
        )
        response = self.api.transactions_get(request)
        out: List[Dict[str, Any]] = []
        for t in response.transactions:
            out.append({
                "txn_id": t.transaction_id,
                "account_id": t.account_id,
                "date": t.date if isinstance(t.date, date) else date.fromisoformat(str(t.date)),
                "name": t.name,
                "amount": float(t.amount),
                "merchant_name": t.merchant_name,
                "category": ", ".join(t.category) if t.category else "",
            })
        return out


# ===== Mock manager for testing =====

class MockPlaidManager:
    """In-memory stub that mirrors the PlaidManager surface for tests/demos."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._accounts: Dict[str, List[Dict[str, Any]]] = {}
        self._transactions: Dict[str, List[Dict[str, Any]]] = {}
        self._public_to_access: Dict[str, str] = {}

    def create_link_token(
        self,
        user_id: str,
        church_name: str,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "link_token": f"link-sandbox-mock-{user_id}",
            "expiration": "2099-01-01T00:00:00Z",
        }

    def exchange_public_token(self, public_token: str) -> str:
        # Deterministic mapping
        access = f"access-sandbox-mock-{public_token[-8:] if len(public_token) >= 8 else public_token}"
        self._public_to_access[public_token] = access
        return access

    def seed_accounts(self, access_token: str, accounts: List[Dict[str, Any]]) -> None:
        self._accounts[access_token] = accounts

    def seed_transactions(self, access_token: str, txns: List[Dict[str, Any]]) -> None:
        self._transactions[access_token] = txns

    def get_accounts(self, access_token: str) -> List[Dict[str, Any]]:
        if access_token in self._accounts:
            return self._accounts[access_token]
        return [{
            "account_id": f"acct-{access_token[-6:]}",
            "name": "Plaid Checking",
            "subtype": "checking",
            "type": "depository",
            "mask": "0000",
            "balances": {"current": 1000.0, "available": 950.0, "limit": None},
        }]

    def get_transactions(
        self,
        access_token: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        if access_token in self._transactions:
            return [
                t for t in self._transactions[access_token]
                if start_date <= t["date"] <= end_date
            ]
        return []


# Module-level helper to swap implementations during testing.
_MANAGER: Optional[Any] = None


def get_manager() -> Any:
    global _MANAGER
    if _MANAGER is not None:
        return _MANAGER
    if os.environ.get("PLAID_USE_MOCK", "").lower() in ("1", "true", "yes"):
        _MANAGER = MockPlaidManager()
        return _MANAGER
    _MANAGER = PlaidManager(env=os.environ.get("PLAID_ENV", "sandbox"))
    return _MANAGER


def set_manager(manager: Any) -> None:
    """Allow tests to inject a mock manager."""
    global _MANAGER
    _MANAGER = manager


def reset_manager() -> None:
    global _MANAGER
    _MANAGER = None
