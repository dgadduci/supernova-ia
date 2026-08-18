"""Server-side JWT validation for Phase 2 Supabase magic-link tokens.

The validator is the single boundary that converts a Supabase-issued
JWT into an :class:`backend.auth.principal.AuthenticatedPrincipal`.
Every required check happens BEFORE any business code runs:

* Signature is verified against the configured JWKS document. The
  helper refuses any token signed with an algorithm outside the
  allowlist; the allowlist itself is restricted to the asymmetric
  set so an operator cannot silently downgrade to HMAC.
* ``iss`` matches the exact configured issuer claim.
* ``aud`` matches the exact configured audience claim
  (``authenticated``).
* ``exp`` is in the future; ``nbf`` is respected when present.
* ``sub`` is a non-empty stripped string.
* The token is structurally well-formed (three dot-separated
  segments with a parseable header and payload).

A failure raises a typed exception that the router translates into a
bounded sign-in-required or service-unavailable view. No exception
detail is ever rendered to the client.

JWKS failures (timeout, parse error, missing ``kid``, unknown
``kid`` or empty key material) fail closed before any business
logic runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import (
    InvalidAlgorithmError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
    PyJWKClient,
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWKSetError,
)
from jwt.exceptions import ExpiredSignatureError, ImmatureSignatureError

from backend.auth.principal import AuthenticatedPrincipal
from backend.auth.settings import SupabaseAuthSettings
from backend.services.exceptions import InvalidSupabaseAuthConfig


@dataclass(frozen=True)
class JwtValidationError(Exception):
    """Raised when a provider JWT fails any Phase 2 validation step.

    The router converts this signal into a bounded sign-in-required
    view (HTTP 401) for expected failures or a generic
    service-unavailable view (HTTP 503) when the JWKS layer itself
    fails. The exception detail is intentionally generic; the
    router never renders the raw reason to the visitor.
    """

    reason: str

    def __str__(self) -> str:  # pragma: no cover - debugging only
        return f"jwt_validation_failed:{self.reason}"


def _resolve_jwks_signing_key(
    settings: SupabaseAuthSettings, token: str
) -> Any:
    """Return the JWKS key matching ``token``'s ``kid``.

    The JWKS client is created per-call so it inherits the bounded
    timeout configured for the Supabase auth layer. Any connection
    or parse failure is collapsed into ``jwks_unavailable`` so the
    router can fail closed without leaking the underlying reason.
    """
    if not settings.jwks_url:
        raise JwtValidationError("jwks_unconfigured")
    try:
        client = PyJWKClient(
            settings.jwks_url,
            timeout=settings.request_timeout_seconds,
            cache_keys=True,
            lifespan=settings.session_max_age_seconds,
        )
        signing_key = client.get_signing_key_from_jwt(token)
    except (
        PyJWKClientConnectionError,
        PyJWKClientError,
        PyJWKSetError,
    ) as exc:
        raise JwtValidationError("jwks_unavailable") from exc
    except InvalidTokenError as exc:
        raise JwtValidationError("token_malformed") from exc
    except Exception as exc:
        raise JwtValidationError("jwks_unavailable") from exc
    key = getattr(signing_key, "key", None)
    if key is None or key == "":
        raise JwtValidationError("jwks_key_empty")
    return key


def _resolve_signing_key(
    settings: SupabaseAuthSettings,
    header: Mapping[str, Any],
    token: str,
) -> Any:
    """Resolve the verification key for ``header``.

    JWKS is the only supported path: the helper picks the key with
    a matching ``kid`` so Supabase's key rotation is honoured. The
    Phase 2 contract forbids HMAC validation, so the helper never
    returns a shared secret.
    """
    if settings.jwks_url:
        return _resolve_jwks_signing_key(settings, token)
    raise JwtValidationError("jwks_unconfigured")


def _header_algorithms(
    settings: SupabaseAuthSettings, header: Mapping[str, Any]
) -> tuple[str, ...]:
    header_alg = header.get("alg")
    if not isinstance(header_alg, str) or not header_alg.strip():
        raise JwtValidationError("algorithm_missing")
    header_alg = header_alg.strip()
    if header_alg not in settings.allowed_algorithms:
        raise JwtValidationError("algorithm_not_allowed")
    return (header_alg,)


def _validate_subject(claims: Mapping[str, Any]) -> str:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise JwtValidationError("subject_missing")
    return subject.strip()


def validate_supabase_jwt(
    token: str,
    *,
    settings: SupabaseAuthSettings,
) -> AuthenticatedPrincipal:
    """Validate ``token`` against the Phase 2 contract.

    The function is the single source of truth for JWT verification:
    every required check (algorithm allowlist, JWKS signature,
    issuer, audience, expiry, subject) is enforced here. A failure
    raises :class:`JwtValidationError` so the router can translate
    it without leaking the underlying reason.

    The token is required to carry the ``sub`` claim. The audience
    is verified as an exact match against the configured value (the
    Supabase ``authenticated`` audience). The issuer is verified as
    an exact match against the configured value. ``exp`` is
    enforced by PyJWT; ``nbf`` is honoured when present.
    """
    if not isinstance(token, str) or not token.strip():
        raise JwtValidationError("token_missing")
    cleaned_token = token.strip()

    if not settings.enabled:
        raise JwtValidationError("feature_disabled")

    try:
        header = jwt.get_unverified_header(cleaned_token)
    except InvalidTokenError as exc:
        raise JwtValidationError("token_malformed") from exc

    algorithms = _header_algorithms(settings, header)
    signing_key = _resolve_signing_key(settings, header, cleaned_token)

    audience = settings.jwt_audience
    issuer = settings.jwt_issuer

    try:
        claims = jwt.decode(
            cleaned_token,
            signing_key,
            algorithms=list(algorithms),
            audience=audience,
            issuer=issuer,
            options={
                "require": ["exp", "iss", "aud"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except ExpiredSignatureError as exc:
        raise JwtValidationError("token_expired") from exc
    except ImmatureSignatureError as exc:
        raise JwtValidationError("token_not_yet_valid") from exc
    except InvalidAudienceError as exc:
        raise JwtValidationError("audience_invalid") from exc
    except InvalidIssuerError as exc:
        raise JwtValidationError("issuer_invalid") from exc
    except (InvalidSignatureError, InvalidAlgorithmError) as exc:
        raise JwtValidationError("signature_invalid") from exc
    except MissingRequiredClaimError as exc:
        raise JwtValidationError("claim_missing") from exc
    except InvalidTokenError as exc:
        raise JwtValidationError("token_malformed") from exc

    subject = _validate_subject(claims)
    return AuthenticatedPrincipal(
        subject=subject,
        issuer=issuer,
        audience=audience,
    )


def build_jwks_client_for_test(
    settings: SupabaseAuthSettings,
) -> PyJWKClient:
    """Build a PyJWKClient for the configured JWKS URL.

    The helper is exposed for tests; production code never imports
    PyJWKClient directly. The helper centralises the timeout so a
    future change to the JWKS layer only happens in one place.
    """
    if not settings.jwks_url:
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_JWKS_URL must be configured to build a JWKS client"
        )
    return PyJWKClient(
        settings.jwks_url,
        timeout=settings.request_timeout_seconds,
        cache_keys=True,
        lifespan=settings.session_max_age_seconds,
    )


__all__ = [
    "JwtValidationError",
    "build_jwks_client_for_test",
    "validate_supabase_jwt",
]