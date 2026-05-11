"""FR-NF-RBAC: Role-based access control for EIME endpoints.

The current EIME deployment is single-tenant per church and runs behind a
trusted reverse proxy. We accept the user's role from a request header
(`X-User-Role`) and an optional email (`X-User-Email`).

Roles (least → most privileged):
  FINANCE_STAFF   — read-only and triage
  BUDGET_OWNER    — corrects + approves at first stage
  TREASURER_ADMIN — posts JEs, approves payments, admin actions

Usage:
    @app.post("/api/jes/{je_id}/post")
    @requires_role("TREASURER_ADMIN")
    async def post_je_to_acs(je_id: str, request: Request) -> JSONResponse:
        ...

The decorator inspects the FastAPI Request kwarg. If the role is missing
or below the required role, raises HTTPException 403.
"""
from __future__ import annotations

import functools
import inspect
from typing import Callable, Iterable, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel


# Role precedence — higher index = more privileged
ROLE_LEVELS = {
    "FINANCE_STAFF": 1,
    "BUDGET_OWNER": 2,
    "TREASURER_ADMIN": 3,
    "ADMIN": 4,
}


def _extract_role(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    # Validate proxy secret if configured (protect against header spoofing in dev)
    import os
    trusted_secret = os.environ.get("TRUSTED_PROXY_SECRET")
    if trusted_secret:
        provided_secret = request.headers.get("x-proxy-secret") or request.headers.get("X-Proxy-Secret")
        if provided_secret != trusted_secret:
            return None  # Role header ignored without valid secret
    role = request.headers.get("x-user-role") or request.headers.get("X-User-Role")
    if role:
        return role.strip().upper()
    return None


def _extract_email(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    return (
        request.headers.get("x-user-email")
        or request.headers.get("X-User-Email")
    )


def has_role(actual: Optional[str], required: str) -> bool:
    if not actual:
        return False
    a = ROLE_LEVELS.get(actual.upper(), 0)
    r = ROLE_LEVELS.get(required.upper(), 0)
    return a >= r


def requires_role(*allowed: str):
    """Decorator: require any of `allowed` roles (or higher) on the request.

    The wrapped endpoint must accept a `request: Request` kwarg.
    """
    if not allowed:
        raise ValueError("requires_role needs at least one role")

    def decorator(fn: Callable) -> Callable:
        sig = inspect.signature(fn)
        is_async = inspect.iscoroutinefunction(fn)

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            request: Optional[Request] = kwargs.get("request")
            if request is None:
                # Try positional Request among args
                for a in args:
                    if isinstance(a, Request):
                        request = a
                        break
            actual = _extract_role(request)
            if not any(has_role(actual, r) for r in allowed):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Forbidden: role '{actual or 'none'}' lacks "
                        f"required role(s): {', '.join(allowed)}"
                    ),
                )
            return await fn(*args, **kwargs)

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            request: Optional[Request] = kwargs.get("request")
            if request is None:
                for a in args:
                    if isinstance(a, Request):
                        request = a
                        break
            actual = _extract_role(request)
            if not any(has_role(actual, r) for r in allowed):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Forbidden: role '{actual or 'none'}' lacks "
                        f"required role(s): {', '.join(allowed)}"
                    ),
                )
            return fn(*args, **kwargs)

        return async_wrapper if is_async else sync_wrapper

    return decorator


def get_caller_role(request: Optional[Request]) -> Optional[str]:
    return _extract_role(request)


def get_caller_email(request: Optional[Request]) -> Optional[str]:
    return _extract_email(request)


class User(BaseModel):
    """Stub user model extracted from request headers."""
    user_id: Optional[str] = None
    role: Optional[str] = None


async def verify_bearer_token(request: Request) -> User:
    """Extract user from request headers (trusted reverse proxy auth)."""
    role = _extract_role(request)
    email = _extract_email(request)
    return User(user_id=email or "unknown", role=role or "FINANCE_STAFF")
