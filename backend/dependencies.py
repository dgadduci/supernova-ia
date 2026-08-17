import hashlib
import hmac
import os
import secrets
from collections.abc import Iterator
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config.database_url import normalize_database_url
from backend.config.settings import load_settings

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
    panel-specific secret is configured so the panel works out of the
    box without a new deployment setting. The secret is normalised
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


__all__ = [
    "ADMIN_TOKEN_HEADER",
    "PANEL_FORM_NONCE_FIELD",
    "compute_panel_form_nonce",
    "get_session",
    "require_admin_browser_basic",
    "require_admin_pilot_basic",
    "require_admin_token",
    "require_same_origin_panel_form",
    "resolve_panel_csrf_secret",
]
