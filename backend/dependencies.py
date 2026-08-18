import hashlib
import hmac
import os
import secrets
from collections.abc import Iterator
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.auth import (
    AuthenticatedPrincipal,
    resolve_supabase_auth_settings,
)
from backend.auth.session import (
    SessionValidationError,
    parse_session_cookie,
)
from backend.config.database_url import normalize_database_url
from backend.config.settings import load_settings
from backend.services.exceptions import InvalidSupabaseAuthConfig

DEFAULT_URL = "postgresql+psycopg:///supernova_test"

_engine = create_engine(
    normalize_database_url(os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL))
)
_SessionLocal = sessionmaker(
    bind=_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_session() -> Iterator[Session]:
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


ADMIN_TOKEN_HEADER = "X-Admin-Token"

_ADMIN_TOKEN_MISSING_DETAIL = "Administrative credential required"
_ADMIN_TOKEN_MISCONFIGURED_DETAIL = (
    "Administrative credential authentication is unavailable"
)


def _coerce_admin_token_header(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned


def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias=ADMIN_TOKEN_HEADER),
) -> None:
    raw_configured = load_settings().order_management_admin_token
    configured_token = (
        raw_configured.strip() if isinstance(raw_configured, str) else None
    )
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ADMIN_TOKEN_MISCONFIGURED_DETAIL,
        )

    presented_token = _coerce_admin_token_header(x_admin_token)
    if presented_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_ADMIN_TOKEN_MISSING_DETAIL,
        )

    if not secrets.compare_digest(presented_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_ADMIN_TOKEN_MISSING_DETAIL,
        )


_browser_basic_security = HTTPBasic(auto_error=False)


def _resolve_browser_admin_token() -> str | None:
    """Return the configured administrative token stripped of
    surrounding whitespace, or ``None`` when missing or blank.

    The helper centralises the validation contract used by every
    browser-admin Basic dependency so the pilot panel and the new
    administrative catalog panel can never diverge on what counts as
    a configured credential.
    """
    raw_configured = load_settings().order_management_admin_token
    if not isinstance(raw_configured, str):
        return None
    configured = raw_configured.strip()
    return configured or None


def _validate_browser_basic_credentials(
    credentials: HTTPBasicCredentials | None,
) -> None:
    """Validate HTTP Basic credentials against the configured admin token.

    The username is ignored and the password is compared in constant
    time against the configured administrative secret. Generic
    ``401`` / ``503`` failures keep the dependency safe to use as a
    public-facing boundary; the helper is the single source of truth
    for both the pilot-order panel and the new administrative catalog
    panel.
    """
    configured_token = _resolve_browser_admin_token()
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ADMIN_TOKEN_MISCONFIGURED_DETAIL,
            headers={"WWW-Authenticate": "Basic"},
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_ADMIN_TOKEN_MISSING_DETAIL,
            headers={"WWW-Authenticate": "Basic"},
        )

    presented_password = credentials.password or ""
    if not secrets.compare_digest(presented_password, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_ADMIN_TOKEN_MISSING_DETAIL,
            headers={"WWW-Authenticate": "Basic"},
        )


def require_admin_browser_basic(
    credentials: Annotated[
        HTTPBasicCredentials | None, Depends(_browser_basic_security)
    ],
) -> None:
    """Validate the browser-only HTTP Basic credential.

    The username is ignored; the password must match the configured
    ``order_management_admin_token`` with a constant-time comparison.
    The header name and the configured token are never echoed back:
    failures reuse the same generic administrative detail used by the
    JSON API dependency, so the panel cannot be used to probe the
    token. The dependency never opens a database session, never logs
    the credential and creates no credential persistence.

    The dependency is the single browser-only Basic boundary shared
    by every panel family (``/admin/pilot/orders`` and
    ``/admin/catalog``). It is intentionally distinct from
    :func:`require_admin_token` so the JSON API contract — every
    non-panel administrative route requires the
    ``X-Admin-Token`` header — stays unchanged.
    """
    _validate_browser_basic_credentials(credentials)


def require_admin_pilot_basic(
    credentials: Annotated[
        HTTPBasicCredentials | None, Depends(_browser_basic_security)
    ],
) -> None:
    """Compatibility alias for the legacy pilot-order panel.

    The pilot-order panel predates the general
    :func:`require_admin_browser_basic` dependency. The new shared
    boundary preserves every documented behaviour: the username is
    ignored, the password is compared in constant time against the
    configured token, and every failure emits the same generic
    ``401`` / ``503`` detail. New code should depend on
    :func:`require_admin_browser_basic` directly.
    """
    _validate_browser_basic_credentials(credentials)


PANEL_FORM_NONCE_FIELD = "_csrf_nonce"
PANEL_FORM_NONCE_MISSING_MESSAGE = (
    "El panel rechazó la solicitud por token CSRF inválido o ausente."
)
PANEL_FORM_ORIGIN_MISSING_MESSAGE = (
    "El panel rechazó la solicitud por falta de encabezado de origen."
)
PANEL_FORM_ORIGIN_MISMATCH_MESSAGE = (
    "El panel rechazó la solicitud por origen no permitido."
)
_PANEL_FORM_PROTECTED_METHODS: frozenset[str] = frozenset(
    {"POST", "PUT", "DELETE", "PATCH"}
)


def _panel_request_origin(request: Request) -> str | None:
    """Return the panel submission origin URL.

    The helper prefers the ``Origin`` header because browsers always
    send it for cross-origin state-changing requests. When the
    ``Origin`` header is missing the helper falls back to the
    ``Referer`` header so older browsers and same-origin requests
    without ``Origin`` continue to validate. The helper returns the
    raw URL string — never the parsed netloc — so the caller can
    decide whether to compare the full URL (for ``Referer``) or the
    bare origin (for ``Origin``).
    """
    origin = request.headers.get("origin")
    if origin:
        cleaned = origin.strip()
        return cleaned or None
    referer = request.headers.get("referer")
    if referer:
        cleaned = referer.strip()
        return cleaned or None
    return None


def _effective_request_origin(request: Request) -> str:
    """Return the ``scheme://host[:port]`` the server sees for the request.

    The helper relies on Starlette's ``request.url`` so it works for
    direct connections and for ASGI servers that propagate the
    original scheme and host. When the operator deploys behind a
    reverse proxy that rewrites ``Host`` / ``X-Forwarded-*``, they
    must pin the panel to an explicit ``ADMIN_PANEL_ALLOWED_ORIGIN``
    so the runtime does not silently accept any origin.
    """
    return f"{request.url.scheme}://{request.url.netloc}"


def _configured_panel_allowed_origin() -> str | None:
    """Return the operator-pinned panel origin or ``None``.

    The helper reads ``ADMIN_PANEL_ALLOWED_ORIGIN`` and strips the
    surrounding whitespace; an unset, blank or non-string value is
    treated as "no explicit pin" so the dependency falls back to the
    effective request origin. The check remains active by default:
    the caller always compares against the request's effective
    origin even when no operator pin is configured.
    """
    raw = load_settings().admin_panel_allowed_origin
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    return cleaned or None


async def require_same_origin_panel_form(request: Request) -> None:
    """Reject state-changing panel submissions that lack a same-origin proof.

    The dependency is the panel-only anti-CSRF control compatible with
    stateless HTTP Basic authentication and native HTML form
    submissions. The protection has two independent requirements that
    must hold for every state-changing submission:

    1. The request body (when form-encoded) must contain the
       ``_csrf_nonce`` form field with the path-bound nonce the
       template emitted when the form was rendered. The dependency
       recomputes the expected nonce from the exact submission path
       and compares it with a constant-time digest comparison so a
       cross-site attacker cannot replay a nonce captured from a
       different route.
    2. The submission must originate from the panel's own origin.
       The dependency reads the ``Origin`` header (preferred) or the
       ``Referer`` header (fallback when ``Origin`` is absent) and
       compares the parsed URL origin against either the operator
       pin ``ADMIN_PANEL_ALLOWED_ORIGIN`` or, when no pin is set,
       the effective ``scheme://host[:port]`` of the request itself.
       The comparison is active by default: missing operator pin
       never weakens the check. A submission that arrives without
       ``Origin`` and without ``Referer`` is always rejected.

    GET / HEAD / OPTIONS requests bypass the dependency so the
    router can stay mounted at prefix scope without breaking
    navigation. The dependency parses the form through Starlette's
    ``request.form()`` helper; the result is cached on the request so
    route-level ``Form()`` parameters reuse the same parse and the
    body is never read twice. Failures are converted into the
    documented generic ``400`` response that never echoes the
    submitted value, the credential, the configured host, the
    session, the database or any exception detail. The dependency
    never opens a database session and never logs the failure.
    """
    method = request.method.upper()
    if method not in _PANEL_FORM_PROTECTED_METHODS:
        return

    try:
        form = await request.form()
    except (ValueError, TypeError, RuntimeError):
        form = None
    submitted_nonce: str | None = None
    if form is not None:
        try:
            raw_value = form.get(PANEL_FORM_NONCE_FIELD)
        except (TypeError, AttributeError):
            raw_value = None
        if isinstance(raw_value, str):
            submitted_nonce = raw_value
        elif raw_value is not None:
            submitted_nonce = str(raw_value)

    expected_nonce = compute_panel_form_nonce(
        path=request.url.path,
        secret=resolve_panel_csrf_secret(),
    )
    if (
        submitted_nonce is None
        or not hmac.compare_digest(
            submitted_nonce.encode("utf-8"),
            expected_nonce.encode("utf-8"),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PANEL_FORM_NONCE_MISSING_MESSAGE,
        )

    submitted_origin = _panel_request_origin(request)
    if submitted_origin is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PANEL_FORM_ORIGIN_MISSING_MESSAGE,
        )

    allowed_origin = _configured_panel_allowed_origin() or _effective_request_origin(
        request
    )
    submitted_origin_parsed = urlparse(submitted_origin)
    submitted_origin_only = (
        f"{submitted_origin_parsed.scheme}://{submitted_origin_parsed.netloc}"
        if submitted_origin_parsed.scheme and submitted_origin_parsed.netloc
        else submitted_origin
    )
    if not hmac.compare_digest(
        submitted_origin_only.encode("utf-8"),
        allowed_origin.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PANEL_FORM_ORIGIN_MISMATCH_MESSAGE,
        )


def compute_panel_form_nonce(*, path: str, secret: bytes) -> str:
    """Return a deterministic form nonce bound to ``path``.

    The helper produces a hex SHA-256 digest keyed by the panel CSRF
    secret and the exact path the form is rendered for. The nonce is
    intentionally non-secret: it travels inside the rendered HTML
    and inside the form payload. Binding it to the path means a
    single rendered form cannot be replayed against an unrelated
    route, so the only way an attacker can submit a valid nonce is to
    either render the form themselves (defeated by the same-origin
    check) or coerce the legitimate browser into issuing the
    request (which the same-origin check also rejects). The helper
    never inspects the request and is safe to call from any template
    context.
    """
    if not isinstance(path, str):
        raise TypeError("path must be a str")
    digest = hashlib.sha256(secret + b"\x00" + path.encode("utf-8")).hexdigest()
    return digest


def resolve_panel_csrf_secret() -> bytes:
    """Return the panel CSRF secret used to sign form nonces.

    The helper reuses the configured administrative token when no
    panel-specific secret is configured so the panel works out of
    the box without a new deployment setting. The secret is normalised
    once so every form nonce is derived from a stable byte sequence.
    The non-secret path-bound nonce plus the same-origin
    proof-of-origin are the actual security boundary; the secret
    only binds a nonce to a single installation so cross-deployment
    replays stay invalid.
    """
    settings = load_settings()
    raw = settings.admin_panel_csrf_secret
    if isinstance(raw, str) and raw.strip():
        return raw.strip().encode("utf-8")
    configured_token = _resolve_browser_admin_token()
    if configured_token is None:
        return b"supernova-panel-csrf-fallback"
    return configured_token.encode("utf-8")


_PHASE2_OWNER_SIGNIN_REQUIRED_DETAIL = (
    "Owner authentication required"
)
_PHASE2_OWNER_FEATURE_DISABLED_DETAIL = (
    "Owner authentication is not configured"
)
_PHASE2_OWNER_CONFIG_INVALID_DETAIL = (
    "Owner authentication is not configured correctly"
)


class _Phase2ConfigInvalid(Exception):
    """Internal signal for an invalid Phase 2 Supabase configuration.

    The router converts this signal into a bounded 503 response.
    The exception detail is intentionally generic and is never
    rendered to the visitor.
    """


def _resolve_phase2_settings() -> Any:
    """Resolve the Phase 2 settings, converting errors into a
    dedicated typed exception that the router can map to a 503."""
    try:
        return resolve_supabase_auth_settings()
    except InvalidSupabaseAuthConfig as exc:
        raise _Phase2ConfigInvalid(str(exc)) from exc


def _resolve_phase2_principal(
    request: Request,
) -> AuthenticatedPrincipal | None:
    """Resolve the Phase 2 principal from the local session cookie.

    The helper is intentionally lenient: a missing cookie returns
    ``None`` and a tampered cookie raises
    :class:`SessionValidationError`. It never opens a database
    session and never logs the cookie value.
    """
    settings = resolve_supabase_auth_settings()
    if not settings.enabled:
        return None
    cookie_header = request.headers.get("cookie")
    headers = {"cookie": cookie_header} if cookie_header else {}
    session = parse_session_cookie(headers, settings=settings)
    if session is None:
        return None
    return AuthenticatedPrincipal(
        subject=session.subject,
        issuer=session.issuer,
        audience=session.audience,
    )


def require_authenticated_owner_principal(
    request: Request,
) -> AuthenticatedPrincipal:
    """Return the authenticated Phase 2 principal or raise.

    The dependency is the single business boundary that produces an
    :class:`backend.auth.AuthenticatedPrincipal` after the local
    session cookie has been validated. It MUST run before any
    owner-scoped business code so a missing / expired / tampered
    cookie can never reach a database query.

    When the feature is disabled the dependency surfaces a ``503``
    with a generic detail so the boundary stays explicit; the
    router is responsible for translating the signal into the
    appropriate view. A configuration error also surfaces a bounded
    ``503`` so the dependency never leaks a 500.

    The dependency never opens a database session, never reads the
    provider JWT directly and never logs the cookie value.
    """
    try:
        settings = _resolve_phase2_settings()
    except _Phase2ConfigInvalid:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_PHASE2_OWNER_CONFIG_INVALID_DETAIL,
        )
    if not settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_PHASE2_OWNER_FEATURE_DISABLED_DETAIL,
        )
    try:
        principal = _resolve_phase2_principal(request)
    except SessionValidationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_PHASE2_OWNER_SIGNIN_REQUIRED_DETAIL,
        )
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_PHASE2_OWNER_SIGNIN_REQUIRED_DETAIL,
        )
    return principal


def try_authenticated_owner_principal(
    request: Request,
) -> AuthenticatedPrincipal | None:
    """Return the Phase 2 principal without raising on failure.

    The dependency is the lenient counterpart to
    :func:`require_authenticated_owner_principal`. It returns
    ``None`` when the feature is disabled, when the configuration
    is invalid, when the cookie is absent, or when the cookie
    fails any validation check. The router is responsible for
    rendering the bounded sign-in-required view in those cases.
    """
    try:
        return _resolve_phase2_principal(request)
    except (SessionValidationError, _Phase2ConfigInvalid):
        return None


def _resolve_owner_onboarding_csrf_secret() -> bytes:
    """Return the Phase 3 owner-onboarding CSRF signing secret.

    The helper reuses the configured administrative token when no
    owner-specific secret is configured so the wizard works out of
    the box without a new deployment setting. The non-secret
    path-bound nonce plus the same-origin proof-of-origin are the
    actual security boundary; the secret only binds a nonce to a
    single installation so cross-deployment replays stay invalid.
    A future Phase 3 hardening can add a dedicated
    ``OWNER_ONBOARDING_CSRF_SECRET`` env so the wizard no longer
    relies on the administrative token.
    """
    settings = load_settings()
    raw = settings.owner_onboarding_csrf_secret
    if isinstance(raw, str) and raw.strip():
        return raw.strip().encode("utf-8")
    configured_token = _resolve_browser_admin_token()
    if configured_token is None:
        return b"supernova-owner-onboarding-csrf-fallback"
    return configured_token.encode("utf-8")


OWNER_FORM_NONCE_FIELD = "_owner_nonce"
OWNER_FORM_NONCE_MISSING_MESSAGE = (
    "El wizard de onboarding rechazó la solicitud por token CSRF "
    "inválido o ausente."
)
OWNER_FORM_ORIGIN_MISSING_MESSAGE = (
    "El wizard de onboarding rechazó la solicitud por falta de "
    "encabezado de origen."
)
OWNER_FORM_ORIGIN_MISMING_MESSAGE = (
    "El wizard de onboarding rechazó la solicitud por origen no "
    "permitido."
)


def compute_owner_onboarding_form_nonce(*, path: str, secret: bytes) -> str:
    """Return the deterministic form nonce for the owner wizard.

    The helper mirrors :func:`compute_panel_form_nonce` but uses the
    owner-onboarding CSRF secret so a nonce stolen from the admin
    panel cannot be replayed against the wizard and vice versa.
    """
    if not isinstance(path, str):
        raise TypeError("path must be a str")
    digest = hashlib.sha256(secret + b"\x00" + path.encode("utf-8")).hexdigest()
    return digest


def _owner_request_origin(request: Request) -> str | None:
    """Return the owner onboarding submission origin URL.

    Mirrors :func:`_panel_request_origin` so the wizard enforces the
    same-origin check on exactly the same headers.
    """
    origin = request.headers.get("origin")
    if origin:
        cleaned = origin.strip()
        return cleaned or None
    referer = request.headers.get("referer")
    if referer:
        cleaned = referer.strip()
        return cleaned or None
    return None


def _owner_configured_allowed_origin() -> str | None:
    """Return the operator-pinned wizard allowed-origin or ``None``.

    Reads ``OWNER_ONBOARDING_ALLOWED_ORIGIN`` when configured; falls
    back to ``ADMIN_PANEL_ALLOWED_ORIGIN`` so an operator who has
    already pinned the panel origin does not need to repeat the
    value for the wizard.
    """
    settings = load_settings()
    raw = settings.owner_onboarding_allowed_origin
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    raw_panel = settings.admin_panel_allowed_origin
    if isinstance(raw_panel, str) and raw_panel.strip():
        return raw_panel.strip()
    return None


async def require_same_origin_owner_onboarding_form(
    request: Request,
) -> None:
    """Reject owner wizard submissions that lack same-origin + CSRF.

    The dependency mirrors
    :func:`require_same_origin_panel_form` for the Phase 3 wizard
    boundary. Two independent checks must hold for every state-
    changing submission:

    1. The form body must carry the ``_owner_nonce`` field whose
       value equals the SHA-256 digest over the submission path
       keyed by the owner-onboarding CSRF secret. The dependency
       recomputes the nonce from the exact path and compares it in
       constant time so a cross-site attacker cannot replay a
       nonce captured from a different wizard path.
    2. The submission must originate from the wizard's own origin.
       The helper reads ``Origin`` (preferred) or ``Referer``
       (fallback) and matches the parsed origin against either the
       ``OWNER_ONBOARDING_ALLOWED_ORIGIN`` pin, the
       ``ADMIN_PANEL_ALLOWED_ORIGIN`` pin, or the effective
       ``scheme://host[:port]`` the request itself. The check
       stays active when no operator pin is configured.

    GET / HEAD / OPTIONS requests bypass the dependency so the
    router can stay mounted without breaking navigation. A
    submission that arrives without ``Origin`` and ``Referer`` is
    always rejected.
    """
    method = request.method.upper()
    if method not in _PANEL_FORM_PROTECTED_METHODS:
        return

    try:
        form = await request.form()
    except (ValueError, TypeError, RuntimeError):
        form = None
    submitted_nonce: str | None = None
    if form is not None:
        try:
            raw_value = form.get(OWNER_FORM_NONCE_FIELD)
        except (TypeError, AttributeError):
            raw_value = None
        if isinstance(raw_value, str):
            submitted_nonce = raw_value
        elif raw_value is not None:
            submitted_nonce = str(raw_value)

    expected_nonce = compute_owner_onboarding_form_nonce(
        path=request.url.path,
        secret=_resolve_owner_onboarding_csrf_secret(),
    )
    if (
        submitted_nonce is None
        or not hmac.compare_digest(
            submitted_nonce.encode("utf-8"),
            expected_nonce.encode("utf-8"),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OWNER_FORM_NONCE_MISSING_MESSAGE,
        )

    submitted_origin = _owner_request_origin(request)
    if submitted_origin is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OWNER_FORM_ORIGIN_MISSING_MESSAGE,
        )

    allowed_origin = _owner_configured_allowed_origin() or _effective_request_origin(
        request
    )
    submitted_origin_parsed = urlparse(submitted_origin)
    submitted_origin_only = (
        f"{submitted_origin_parsed.scheme}://{submitted_origin_parsed.netloc}"
        if submitted_origin_parsed.scheme and submitted_origin_parsed.netloc
        else submitted_origin
    )
    if not hmac.compare_digest(
        submitted_origin_only.encode("utf-8"),
        allowed_origin.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OWNER_FORM_ORIGIN_MISMING_MESSAGE,
        )


__all__ = [
    "ADMIN_TOKEN_HEADER",
    "OWNER_FORM_NONCE_FIELD",
    "PANEL_FORM_NONCE_FIELD",
    "compute_owner_onboarding_form_nonce",
    "compute_panel_form_nonce",
    "get_session",
    "require_admin_browser_basic",
    "require_admin_pilot_basic",
    "require_admin_token",
    "require_authenticated_owner_principal",
    "require_same_origin_owner_onboarding_form",
    "require_same_origin_panel_form",
    "resolve_panel_csrf_secret",
    "try_authenticated_owner_principal",
]
