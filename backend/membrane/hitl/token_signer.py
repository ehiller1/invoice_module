"""HITLTokenSigner — RSA sign/verify with key rotation cache.

A new RSA-2048 key pair is generated lazily; rotation pushes the active key
into a bounded LRU cache so recently-issued tokens still verify after rotation.
Tokens older than `ttl_seconds` are rejected at verify time.
"""
from __future__ import annotations

import base64
import json
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature

from .decision_token import DecisionToken


class InvalidSignatureError(Exception):
    """Raised when a DecisionToken signature does not verify."""


class TokenExpiredError(Exception):
    """Raised when a DecisionToken's timestamp is outside the TTL window."""


class UnknownKeyError(Exception):
    """Raised when the key_id referenced by a token is not in the rotation cache."""


# Allowed forward clock skew for token timestamps (defends against rogue clients
# minting tokens dated in the future).
_FUTURE_SKEW_SECONDS = 300  # 5 minutes


def _canonical_json(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class _KeyEntry:
    __slots__ = ("private_key", "public_key", "created_at")

    def __init__(self, private_key: rsa.RSAPrivateKey) -> None:
        self.private_key = private_key
        self.public_key = private_key.public_key()
        self.created_at = datetime.now(tz=timezone.utc)


class HITLTokenSigner:
    """RSA signer with bounded key-rotation cache."""

    def __init__(self, ttl_seconds: int = 86_400, max_keys: int = 10) -> None:
        self.ttl_seconds = int(ttl_seconds)
        self.max_keys = max(1, int(max_keys))
        self._keys: "OrderedDict[str, _KeyEntry]" = OrderedDict()
        self._active_key_id: Optional[str] = None
        self._mint_new_key()

    # ------------------------------------------------------------------ keys
    def _mint_new_key(self) -> str:
        key_id = f"hitl-{uuid.uuid4().hex[:12]}"
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._keys[key_id] = _KeyEntry(private_key)
        self._active_key_id = key_id
        while len(self._keys) > self.max_keys:
            self._keys.popitem(last=False)  # FIFO eviction of oldest key
        return key_id

    def rotate_key(self) -> str:
        """Force minting of a new active key. Returns the new key_id."""
        return self._mint_new_key()

    @property
    def active_key_id(self) -> str:
        assert self._active_key_id is not None
        return self._active_key_id

    # --------------------------------------------------------------- signing
    def sign(self, payload: Dict[str, Any]) -> DecisionToken:
        """Sign a payload dict and return a DecisionToken.

        Required keys in payload: episode_id, principal, decision, timestamp.
        Optional: reasoning.
        """
        key_id = self.active_key_id
        body = {
            "episode_id": payload["episode_id"],
            "principal": payload["principal"],
            "decision": payload["decision"],
            "reasoning": payload.get("reasoning", ""),
            "timestamp": payload["timestamp"],
            "key_id": key_id,
        }
        priv = self._keys[key_id].private_key
        sig_bytes = priv.sign(
            _canonical_json(body),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        signature_b64 = base64.b64encode(sig_bytes).decode("ascii")
        return DecisionToken(signature=signature_b64, **body)

    # ----------------------------------------------------------- verification
    def verify(self, token: DecisionToken) -> DecisionToken:
        """Verify a token. Returns it on success; raises on failure."""
        entry = self._keys.get(token.key_id)
        if entry is None:
            raise UnknownKeyError(f"unknown key_id: {token.key_id}")

        # Time window check.
        try:
            ts = datetime.fromisoformat(token.timestamp)
        except ValueError as exc:
            raise InvalidSignatureError(f"bad timestamp: {exc}") from exc
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        if ts > now + timedelta(seconds=_FUTURE_SKEW_SECONDS):
            raise TokenExpiredError("token timestamp is in the future beyond allowed skew")
        if now - ts > timedelta(seconds=self.ttl_seconds):
            raise TokenExpiredError("token expired")

        # Signature check.
        try:
            sig_bytes = base64.b64decode(token.signature.encode("ascii"), validate=True)
        except Exception as exc:
            raise InvalidSignatureError(f"signature not base64: {exc}") from exc

        try:
            entry.public_key.verify(
                sig_bytes,
                _canonical_json(token.signed_payload()),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256(),
            )
        except InvalidSignature as exc:
            raise InvalidSignatureError("signature failed verification") from exc
        return token

    # ---------------------------------------------------------------- export
    def public_key_pem(self, key_id: Optional[str] = None) -> bytes:
        kid = key_id or self.active_key_id
        return self._keys[kid].public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )


# ----------------------------------------------------------- module singleton
_default_signer: Optional[HITLTokenSigner] = None


def get_default_signer() -> HITLTokenSigner:
    global _default_signer
    if _default_signer is None:
        _default_signer = HITLTokenSigner()
    return _default_signer


def reset_default_signer_for_tests() -> None:
    global _default_signer
    _default_signer = None


__all__ = [
    "HITLTokenSigner",
    "InvalidSignatureError",
    "TokenExpiredError",
    "UnknownKeyError",
    "get_default_signer",
    "reset_default_signer_for_tests",
]
