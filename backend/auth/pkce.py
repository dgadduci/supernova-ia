"""Server-side PKCE state for Phase 2 Supabase magic-link.

The helper owns the deterministic ``code_verifier`` /
``code_challenge`` pair the server uses to bind the magic-link
request to its callback. The verifier is generated with
``secrets.token_urlsafe`` (cryptographically secure), normalised to
the documented PKCE alphabet and hashed to derive the matching
challenge.

The verifier itself never leaves the application: it is stored in a
short-lived signed temp cookie (:class:`PkceTempCookie`) that the
callback reads and forwards to the Supabase ``/auth/v1/token``
exchange endpoint. The cookie is intentionally narrow:

* the value is the verifier only;
* the cookie is signed with the same session secret as the local
  session, with an explicit ``exp`` claim so it cannot outlive the
  magic-link email it pairs with;
* ``Max-Age`` is bounded through
  :attr:`SupabaseAuthSettings.pkce_cookie_max_age_seconds` so a
  replay window cannot be widened at runtime.

The module never persists the verifier to disk or to any database.
It never logs the verifier, the challenge or the cookie value. The
``encode`` helper strips the value before serialising so the
encoded payload never carries whitespace.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass

from backend.auth.settings import SupabaseAuthSettings

PKCE_VERIFIER_LENGTH = 64
PKCE_COOKIE_NAME = "novaorders_owner_pkce"


@dataclass(frozen=True)
class PkcePair:
    """The verifier / challenge pair for a single magic-link flow.

    Attributes:
        verifier: URL-safe random string used at the token-exchange
            step. The router never renders this value to the visitor
            and never persists it; it only lives in the temp cookie
            between the request and the callback.
        challenge: Base64url SHA-256 digest of the verifier. The
            router embeds the challenge in the OTP request so the
            callback can prove the verifier came from the same flow.
        method: Challenge method identifier. The helper always emits
            ``S256`` because Supabase only accepts SHA-256 challenges.
    """

    verifier: str
    challenge: str
    method: str


@dataclass(frozen=True)
class PkceTempCookie:
    """The decoded content of the PKCE temp cookie.

    Attributes:
        verifier: The PKCE verifier stored for the matching callback.
        issued_at: Unix timestamp at which the cookie was minted.
        expires_at: Unix timestamp at which the cookie becomes
            invalid. The router rejects cookies whose ``expires_at``
            is already in the past so a replay cannot outlive the
            magic-link email.
    """

    verifier: str
    issued_at: int
    expires_at: int

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


def generate_pkce_pair() -> PkcePair:
    """Return a fresh ``code_verifier`` / ``code_challenge`` pair.

    The helper uses :func:`secrets.token_urlsafe` to generate a
    cryptographically secure 64-character verifier. The challenge is
    the URL-safe base64 SHA-256 digest of the verifier (without
    padding) so it matches the documented Supabase ``S256`` contract.
    """
    verifier = secrets.token_urlsafe(PKCE_VERIFIER_LENGTH)
    if not verifier:
        raise RuntimeError("PKCE verifier generation failed")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(verifier=verifier, challenge=challenge, method="S256")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _signing_secret(settings: SupabaseAuthSettings) -> bytes:
    if not settings.session_secret:
        raise RuntimeError("local session secret must be configured")
    return hashlib.sha256(
        settings.session_secret.encode("utf-8")
    ).digest()


def encode_pkce_cookie(
    *, pair: PkcePair, settings: SupabaseAuthSettings
) -> str:
    """Return the encoded PKCE cookie value for ``pair``.

    The value is a base64url-encoded JSON document followed by a
    ``.`` separator and a hex HMAC-SHA256 signature. The signature
    is computed with the configured session secret so a tampered
    cookie can be rejected before the verifier reaches the token
    exchange.
    """
    now = int(time.time())
    payload = {
        "v": pair.verifier,
        "iat": now,
        "exp": now + settings.pkce_cookie_max_age_seconds,
    }
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    signature = hmac.new(
        _signing_secret(settings),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded_payload}.{signature}"


def decode_pkce_cookie(
    raw_value: str, *, settings: SupabaseAuthSettings
) -> PkceTempCookie:
    """Decode and verify ``raw_value`` into a :class:`PkceTempCookie`.

    The helper raises :class:`PkceValidationError` for every failure
    (signature mismatch, malformed value, expired cookie) so the
    router can map the failure to a bounded sign-in-required view.
    No exception detail is ever rendered to the visitor.
    """
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise PkceValidationError("cookie_missing")
    cleaned = raw_value.strip()
    if "." not in cleaned:
        raise PkceValidationError("cookie_malformed")
    encoded_payload, _, signature = cleaned.rpartition(".")
    if not encoded_payload or not signature:
        raise PkceValidationError("cookie_malformed")
    expected_signature = hmac.new(
        _signing_secret(settings),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(
        signature.encode("ascii"), expected_signature.encode("ascii")
    ):
        raise PkceValidationError("signature_invalid")
    try:
        decoded = json.loads(_b64decode(encoded_payload))
    except (ValueError, TypeError):
        raise PkceValidationError("payload_malformed")
    if not isinstance(decoded, Mapping):
        raise PkceValidationError("payload_malformed")
    try:
        verifier = str(decoded["v"]).strip()
        issued_at = int(decoded["iat"])
        expires_at = int(decoded["exp"])
    except (KeyError, TypeError, ValueError):
        raise PkceValidationError("payload_malformed")
    if not verifier:
        raise PkceValidationError("payload_malformed")
    if expires_at <= issued_at:
        raise PkceValidationError("payload_malformed")
    cookie = PkceTempCookie(
        verifier=verifier,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    if cookie.is_expired:
        raise PkceValidationError("cookie_expired")
    return cookie


def build_pkce_cookie_header(
    *, value: str, settings: SupabaseAuthSettings, request_is_secure: bool
) -> str:
    """Build the ``Set-Cookie`` header for the PKCE temp cookie.

    The header always carries ``HttpOnly`` and ``SameSite=Lax``.
    ``Secure`` is appended when the request was served over HTTPS.
    The PKCE cookie is bound to the callback path so it is not
    re-sent on unrelated routes.
    """
    parts = [
        f"{PKCE_COOKIE_NAME}={value}",
        "Path=/auth/callback",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={settings.pkce_cookie_max_age_seconds}",
    ]
    if request_is_secure:
        parts.append("Secure")
    return "; ".join(parts)


def build_clear_pkce_cookie_header(*, request_is_secure: bool) -> str:
    """Build the ``Set-Cookie`` header that clears the PKCE cookie."""
    parts = [
        f"{PKCE_COOKIE_NAME}=",
        "Path=/auth/callback",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if request_is_secure:
        parts.append("Secure")
    return "; ".join(parts)


def parse_pkce_cookie(
    headers: Mapping[str, str], *, settings: SupabaseAuthSettings
) -> PkceTempCookie | None:
    """Return the decoded PKCE cookie or ``None`` if absent.

    A present-but-malformed cookie raises :class:`PkceValidationError`
    so the router can clear it before any further work.
    """
    raw = headers.get("cookie")
    if not raw:
        return None
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if not sep:
            continue
        if key.strip() == PKCE_COOKIE_NAME:
            return decode_pkce_cookie(value.strip(), settings=settings)
    return None


class PkceValidationError(Exception):
    """Raised when the PKCE temp cookie fails any check."""

    reason: str

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


__all__ = [
    "PKCE_COOKIE_NAME",
    "PKCE_VERIFIER_LENGTH",
    "PkcePair",
    "PkceTempCookie",
    "PkceValidationError",
    "build_clear_pkce_cookie_header",
    "build_pkce_cookie_header",
    "decode_pkce_cookie",
    "encode_pkce_cookie",
    "generate_pkce_pair",
    "parse_pkce_cookie",
]