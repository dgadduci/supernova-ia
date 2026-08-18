"""Resolved, fail-closed Supabase magic-link configuration.

The :class:`SupabaseAuthSettings` dataclass is the single
configuration contract for the Phase 2 router. It is resolved on
demand by :func:`resolve_supabase_auth_settings` so the helper can
short-circuit before any application code calls Supabase Auth.

The resolver never accepts a partial configuration. When the
operator turns the feature on (``SUPABASE_AUTH_ENABLED=1``) every
required value must already be present, valid and pinned to a
canonical shape. Any missing or malformed input raises
:class:`backend.services.exceptions.InvalidSupabaseAuthConfig` so
the process startup fails closed.

Phase 2 mandates an asymmetric signature contract:

* The JWT verification path uses JWKS only; no HMAC shared secret
  is accepted.
* The allowlisted algorithms are limited to the asymmetric
  algorithms Supabase actually emits for the user session
  (``ES256``, ``RS256``, ``PS256``, ``EdDSA``).
* The abuse guard is a verifiable, signed dependency; an in-process
  permissive fallback is never accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from backend.config.settings import Settings, load_settings
from backend.services.exceptions import InvalidSupabaseAuthConfig

SUPABASE_CALLBACK_PATH = "/auth/callback"
SUPABASE_OTP_ENDPOINT = "/auth/v1/otp"
SUPABASE_TOKEN_ENDPOINT = "/auth/v1/token"
SUPABASE_AUTH_AUDIENCE = "authenticated"

DEFAULT_ASYMMETRIC_ALGORITHMS: tuple[str, ...] = (
    "ES256",
    "RS256",
    "PS256",
    "EdDSA",
)


@dataclass(frozen=True)
class SupabaseAuthSettings:
    """Resolved, fail-closed configuration for Phase 2 Supabase auth.

    Attributes:
        enabled: Whether the router may issue or accept sessions.
        project_url: Canonical ``https://`` Supabase project URL.
        jwt_issuer: Exact issuer claim expected on the JWT.
        jwt_audience: Exact audience claim expected on the JWT.
        callback_url: Pinned HTTPS callback URL — the only URL the
            provider is allowed to redirect to.
        callback_path: Path component of ``callback_url``; the
            router enforces a single literal route at this path.
        jwks_url: JWKS endpoint URL used for asymmetric signature
            verification. Required when the feature is enabled.
        publishable_key: Publishable / anon key used only for the
            OTP/link request — never for verification.
        session_secret: Secret used to sign the short-lived local
            session cookie and the PKCE temp cookie.
        session_max_age_seconds: Bounded lifetime for the local
            session cookie.
        pkce_cookie_max_age_seconds: Bounded lifetime for the PKCE
            temp cookie issued when requesting a magic link.
        allowed_algorithms: Allowlisted JWT signing algorithms. The
            helper exposes only the asymmetric set so an operator
            cannot silently downgrade to HMAC.
        abuse_guard_url: HTTPS URL for the edge/hosting rate-limit
            gate. The application must call this endpoint before any
            Supabase OTP request; a missing URL is a fail-closed
            signal.
        abuse_guard_token: Bearer token presented to the abuse guard
            so the upstream gate can authenticate the application.
        request_timeout_seconds: Bounded timeout for outbound calls
            to Supabase and the abuse guard.
    """

    enabled: bool
    project_url: str
    jwt_issuer: str
    jwt_audience: str
    callback_url: str
    callback_path: str
    jwks_url: str
    publishable_key: str
    session_secret: str
    session_max_age_seconds: int
    pkce_cookie_max_age_seconds: int
    allowed_algorithms: tuple[str, ...]
    abuse_guard_url: str | None
    abuse_guard_token: str | None
    request_timeout_seconds: int

    @property
    def otp_endpoint(self) -> str:
        """Return the absolute Supabase OTP request URL."""
        return f"{self.project_url.rstrip('/')}{SUPABASE_OTP_ENDPOINT}"

    @property
    def token_endpoint(self) -> str:
        """Return the absolute Supabase PKCE token-exchange URL."""
        return f"{self.project_url.rstrip('/')}{SUPABASE_TOKEN_ENDPOINT}"


def _require_non_empty(name: str, value: str | None) -> str:
    if value is None:
        raise InvalidSupabaseAuthConfig(
            f"{name} must be configured when SUPABASE_AUTH_ENABLED is true"
        )
    if not isinstance(value, str):
        raise InvalidSupabaseAuthConfig(
            f"{name} must be a string when SUPABASE_AUTH_ENABLED is true"
        )
    cleaned = value.strip()
    if not cleaned:
        raise InvalidSupabaseAuthConfig(
            f"{name} must be a non-empty string when SUPABASE_AUTH_ENABLED is true"
        )
    return cleaned


def _validate_callback_url(callback_url: str) -> str:
    parsed = urlparse(callback_url)
    if parsed.scheme.lower() != "https":
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_CALLBACK_URL must use the https scheme "
            f"(got {callback_url!r})"
        )
    if not parsed.netloc:
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_CALLBACK_URL must be an absolute https URL "
            f"(got {callback_url!r})"
        )
    if parsed.query or parsed.fragment:
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_CALLBACK_URL must not contain a query string or fragment "
            f"(got {callback_url!r})"
        )
    if parsed.path != SUPABASE_CALLBACK_PATH:
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_CALLBACK_URL must anchor at "
            f"{SUPABASE_CALLBACK_PATH!r} (got {parsed.path!r})"
        )
    return callback_url


def _validate_jwt_audience(audience: str) -> str:
    cleaned = audience.strip()
    if not cleaned:
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_JWT_AUDIENCE must be a non-empty string"
        )
    if cleaned != SUPABASE_AUTH_AUDIENCE:
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_JWT_AUDIENCE must equal "
            f"{SUPABASE_AUTH_AUDIENCE!r} (got {cleaned!r})"
        )
    return cleaned


def _validate_algorithms(algorithms: tuple[str, ...]) -> tuple[str, ...]:
    if not algorithms:
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_ALLOWED_ALGORITHMS must be a non-empty tuple"
        )
    cleaned: list[str] = []
    for entry in algorithms:
        if not isinstance(entry, str):
            raise InvalidSupabaseAuthConfig(
                "SUPABASE_ALLOWED_ALGORITHMS must contain only strings"
            )
        candidate = entry.strip()
        if not candidate:
            raise InvalidSupabaseAuthConfig(
                "SUPABASE_ALLOWED_ALGORITHMS must contain only "
                "non-empty strings"
            )
        if candidate in cleaned:
            continue
        cleaned.append(candidate)
    if any(alg in {"HS256", "HS384", "HS512"} for alg in cleaned):
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_ALLOWED_ALGORITHMS must not include HMAC "
            "algorithms; JWKS asymmetric verification is the only "
            "supported path"
        )
    asymmetric_set = set(DEFAULT_ASYMMETRIC_ALGORITHMS)
    for alg in cleaned:
        if alg not in asymmetric_set:
            raise InvalidSupabaseAuthConfig(
                "SUPABASE_ALLOWED_ALGORITHMS contains an unsupported "
                f"asymmetric algorithm: {alg!r}"
            )
    return tuple(cleaned)


def resolve_supabase_auth_settings(
    settings: Settings | None = None,
) -> SupabaseAuthSettings:
    """Resolve the Supabase auth configuration from ``settings``.

    When ``SUPABASE_AUTH_ENABLED`` is false the helper returns a
    disabled configuration so callers can short-circuit without
    raising. When the feature is enabled every required value is
    resolved and validated; a missing or malformed value raises
    :class:`InvalidSupabaseAuthConfig` and the router never reaches
    the link request / callback path.
    """
    resolved = settings if settings is not None else load_settings()
    if not resolved.supabase_auth_enabled:
        return SupabaseAuthSettings(
            enabled=False,
            project_url="",
            jwt_issuer="",
            jwt_audience=SUPABASE_AUTH_AUDIENCE,
            callback_url="",
            callback_path=SUPABASE_CALLBACK_PATH,
            jwks_url="",
            publishable_key="",
            session_secret="",
            session_max_age_seconds=resolved.supabase_session_max_age_seconds,
            pkce_cookie_max_age_seconds=(
                resolved.supabase_pkce_cookie_max_age_seconds
            ),
            allowed_algorithms=DEFAULT_ASYMMETRIC_ALGORITHMS,
            abuse_guard_url=None,
            abuse_guard_token=None,
            request_timeout_seconds=(
                resolved.supabase_request_timeout_seconds
            ),
        )

    project_url = _require_non_empty(
        "SUPABASE_PROJECT_URL", resolved.supabase_project_url
    )
    callback_url = _require_non_empty(
        "SUPABASE_CALLBACK_URL", resolved.supabase_callback_url
    )
    _validate_callback_url(callback_url)
    jwks_url = _require_non_empty(
        "SUPABASE_JWKS_URL", resolved.supabase_jwks_url
    )
    publishable_key = _require_non_empty(
        "SUPABASE_PUBLISHABLE_KEY", resolved.supabase_publishable_key
    )
    session_secret = _require_non_empty(
        "SUPABASE_SESSION_SECRET", resolved.supabase_session_secret
    )
    audience = _validate_jwt_audience(resolved.supabase_jwt_audience)
    algorithms = _validate_algorithms(resolved.supabase_allowed_algorithms)

    abuse_guard_url_value = resolved.supabase_abuse_guard_url
    if isinstance(abuse_guard_url_value, str):
        cleaned_guard_url = abuse_guard_url_value.strip() or None
    else:
        cleaned_guard_url = None

    abuse_guard_token_value = resolved.supabase_abuse_guard_token
    if isinstance(abuse_guard_token_value, str):
        cleaned_guard_token = abuse_guard_token_value.strip() or None
    else:
        cleaned_guard_token = None

    if (cleaned_guard_url is None) != (cleaned_guard_token is None):
        raise InvalidSupabaseAuthConfig(
            "SUPABASE_ABUSE_GUARD_URL and SUPABASE_ABUSE_GUARD_TOKEN "
            "must both be configured or both be absent"
        )

    issuer = resolved.supabase_jwt_issuer
    if issuer is None or not str(issuer).strip():
        expected_issuer = f"{project_url.rstrip('/')}/auth/v1"
        issuer = expected_issuer
    else:
        issuer = str(issuer).strip()
        expected_issuer = f"{project_url.rstrip('/')}/auth/v1"
        if issuer != expected_issuer:
            raise InvalidSupabaseAuthConfig(
                "SUPABASE_JWT_ISSUER must equal "
                f"{expected_issuer!r} (got {issuer!r})"
            )

    return SupabaseAuthSettings(
        enabled=True,
        project_url=project_url,
        jwt_issuer=issuer,
        jwt_audience=audience,
        callback_url=callback_url,
        callback_path=SUPABASE_CALLBACK_PATH,
        jwks_url=jwks_url,
        publishable_key=publishable_key,
        session_secret=session_secret,
        session_max_age_seconds=resolved.supabase_session_max_age_seconds,
        pkce_cookie_max_age_seconds=(
            resolved.supabase_pkce_cookie_max_age_seconds
        ),
        allowed_algorithms=algorithms,
        abuse_guard_url=cleaned_guard_url,
        abuse_guard_token=cleaned_guard_token,
        request_timeout_seconds=(
            resolved.supabase_request_timeout_seconds
        ),
    )


__all__ = [
    "DEFAULT_ASYMMETRIC_ALGORITHMS",
    "SUPABASE_AUTH_AUDIENCE",
    "SUPABASE_CALLBACK_PATH",
    "SUPABASE_OTP_ENDPOINT",
    "SUPABASE_TOKEN_ENDPOINT",
    "SupabaseAuthSettings",
    "resolve_supabase_auth_settings",
]