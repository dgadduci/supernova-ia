"""Short-lived local session cookie management.

Phase 2 issues a single ``HttpOnly``, ``Secure``, ``SameSite=Lax``
cookie carrying the validated principal subject. The cookie is
signed with a dedicated HMAC secret so the runtime can detect
tampering and reject the request before any business code runs.

The session is intentionally minimal:

* It carries the subject, the issuer and the audience so the
  runtime can re-verify the principal against the configured
  Supabase contract on every authenticated request.
* It carries an explicit ``exp`` field so a long-lived JWT cannot
  outlive the local session.
* It carries an ``iat`` field so the runtime can reject sessions
  older than the configured bound even if the cookie is replayed.

The cookie value is base64url-encoded JSON. The cookie header is
built with explicit flag strings so the response writer cannot
accidentally downgrade the security profile.

The Phase 2 contract forbids issuing the authenticated cookie over a
plain HTTP request: :func:`build_cookie_header` raises when
``request_is_secure`` is ``False`` so the callback can never mint a
session under a non-HTTPS scheme.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass

from backend.auth.principal import AuthenticatedPrincipal
from backend.auth.settings import SupabaseAuthSettings

SESSION_COOKIE_NAME = "novaorders_owner_session"
SESSION_COOKIE_PATH = "/"
SESSION_COOKIE_SAMESITE = "lax"


@dataclass(frozen=True)
class LocalSession:
    """The decoded content of the local session cookie.

    Attributes:
        subject: Validated external subject.
        issuer: Validated issuer.
        audience: Validated audience.
        issued_at: Unix timestamp at which the cookie was minted.
        expires_at: Unix timestamp at which the cookie becomes
            invalid. The router rejects cookies whose ``expires_at``
            is already in the past.
    """

    subject: str
    issuer: str
    audience: str
    issued_at: int
    expires_at: int

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class InsecureCookieDeliveryError(Exception):
    """Raised when the session cookie would be issued over HTTP."""

    reason: str = "insecure_request"


def _signing_secret(settings: SupabaseAuthSettings) -> bytes:
    if not settings.session_secret:
        raise RuntimeError("local session secret must be configured")
    return hashlib.sha256(
        settings.session_secret.encode("utf-8")
    ).digest()


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def encode_session(
    principal: AuthenticatedPrincipal, *, settings: SupabaseAuthSettings
) -> str:
    """Return the encoded cookie value for ``principal``.

    The value is a base64url-encoded JSON document followed by a
    ``.`` separator and a hex HMAC-SHA256 signature. The signature
    is computed with the configured session secret so a tampered
    cookie can be rejected before any business code runs.
    """
    now = int(time.time())
    payload = {
        "sub": principal.subject,
        "iss": principal.issuer,
        "aud": principal.audience,
        "iat": now,
        "exp": now + settings.session_max_age_seconds,
    }
    encoded_payload = _b64encode(
        json.dumps(
            payload, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    )
    signature = hmac.new(
        _signing_secret(settings),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded_payload}.{signature}"


def decode_session(
    raw_value: str, *, settings: SupabaseAuthSettings
) -> LocalSession:
    """Decode and verify ``raw_value`` into a :class:`LocalSession`.

    The helper raises :class:`SessionValidationError` for every
    failure (signature mismatch, malformed value, expired cookie)
    so the router can map the failure to a bounded sign-in-required
    view. No exception detail is ever rendered to the visitor.
    """
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise SessionValidationError("cookie_missing")
    cleaned = raw_value.strip()
    if "." not in cleaned:
        raise SessionValidationError("cookie_malformed")
    encoded_payload, _, signature = cleaned.rpartition(".")
    if not encoded_payload or not signature:
        raise SessionValidationError("cookie_malformed")
    expected_signature = hmac.new(
        _signing_secret(settings),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(
        signature.encode("ascii"), expected_signature.encode("ascii")
    ):
        raise SessionValidationError("signature_invalid")
    try:
        decoded = json.loads(_b64decode(encoded_payload))
    except (ValueError, TypeError):
        raise SessionValidationError("payload_malformed")
    if not isinstance(decoded, Mapping):
        raise SessionValidationError("payload_malformed")
    try:
        subject = str(decoded["sub"]).strip()
        issuer = str(decoded["iss"]).strip()
        audience = str(decoded["aud"]).strip()
        issued_at = int(decoded["iat"])
        expires_at = int(decoded["exp"])
    except (KeyError, TypeError, ValueError):
        raise SessionValidationError("payload_malformed")
    if not subject or not issuer or not audience:
        raise SessionValidationError("payload_malformed")
    if expires_at <= issued_at:
        raise SessionValidationError("payload_malformed")
    session = LocalSession(
        subject=subject,
        issuer=issuer,
        audience=audience,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    if session.is_expired:
        raise SessionValidationError("session_expired")
    if session.issuer != settings.jwt_issuer:
        raise SessionValidationError("issuer_mismatch")
    if session.audience != settings.jwt_audience:
        raise SessionValidationError("audience_mismatch")
    return session


def build_cookie_header(
    *,
    value: str,
    settings: SupabaseAuthSettings,
    request_is_secure: bool,
) -> str:
    """Build the ``Set-Cookie`` header for ``value``.

    The header always carries ``HttpOnly`` and ``SameSite=Lax``.
    ``Secure`` is appended when the request was served over HTTPS.

    The Phase 2 contract refuses to issue an authenticated cookie
    over a non-HTTPS request: when ``request_is_secure`` is
    ``False`` the helper raises
    :class:`InsecureCookieDeliveryError` so the caller can fail
    closed without ever rendering a downgradeable cookie.
    """
    if not request_is_secure:
        raise InsecureCookieDeliveryError("insecure_request")
    parts = [
        f"{SESSION_COOKIE_NAME}={value}",
        f"Path={SESSION_COOKIE_PATH}",
        "HttpOnly",
        f"SameSite={SESSION_COOKIE_SAMESITE}",
        f"Max-Age={settings.session_max_age_seconds}",
        "Secure",
    ]
    return "; ".join(parts)


def build_clear_cookie_header(*, request_is_secure: bool) -> str:
    """Build the ``Set-Cookie`` header that clears the session.

    The helper emits the documented flags with ``Max-Age=0`` so the
    browser removes the cookie regardless of its remaining lifetime.
    The clear header keeps ``Secure`` whenever the request was
    served over HTTPS so an HTTP downgrade cannot extend the cookie.
    """
    parts = [
        f"{SESSION_COOKIE_NAME}=",
        f"Path={SESSION_COOKIE_PATH}",
        "HttpOnly",
        f"SameSite={SESSION_COOKIE_SAMESITE}",
        "Max-Age=0",
    ]
    if request_is_secure:
        parts.append("Secure")
    return "; ".join(parts)


def parse_session_cookie(
    headers: Mapping[str, str], *, settings: SupabaseAuthSettings
) -> LocalSession | None:
    """Return the decoded session or ``None`` if the cookie is absent.

    The helper is tolerant: an absent cookie returns ``None``; a
    present but malformed cookie raises
    :class:`SessionValidationError` so the router can clear it.
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
        if key.strip() == SESSION_COOKIE_NAME:
            return decode_session(value.strip(), settings=settings)
    return None


class SessionValidationError(Exception):
    """Raised when the local session cookie fails any check.

    The router converts this signal into a bounded sign-in-required
    view. The exception detail is intentionally generic and is
    never rendered to the visitor.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


__all__ = [
    "SESSION_COOKIE_NAME",
    "SESSION_COOKIE_PATH",
    "SESSION_COOKIE_SAMESITE",
    "InsecureCookieDeliveryError",
    "LocalSession",
    "SessionValidationError",
    "build_clear_cookie_header",
    "build_cookie_header",
    "decode_session",
    "encode_session",
    "parse_session_cookie",
]