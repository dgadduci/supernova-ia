"""Public acquisition surface for the NovaOrders self-service trial.

This router is the only public, unauthenticated entry point added
by the ``add-commerce-self-service-onboarding`` change. It exposes
the documented server-rendered Jinja pages and the Phase 2
passwordless identity boundary.

Phase 1 surface (always available):

* ``GET /`` renders the public landing page with hero, benefits,
  planned flow and the primary ``Próximamente`` CTA.
* ``GET /comenzar`` renders the email request form. When the
  Supabase feature is disabled the form falls back to the
  not-enabled placeholder copy.

Phase 2 surface (feature-gated):

* ``POST /comenzar`` issues the Supabase magic-link OTP request.
  The response is always the same neutral confirmation view; the
  helper never reveals whether the email is recognized. The
  request always carries the server-issued PKCE challenge and the
  verifier is stored in a short-lived signed temp cookie.
* ``GET /auth/callback`` exchanges the one-time ``code`` for an
  access JWT through the documented Supabase PKCE token endpoint,
  validates the JWT through the JWKS asymmetric contract, sets a
  short-lived local session and redirects to the bounded
  ``/auth/verificado`` view with a clean URL. The endpoint refuses
  to mint a session cookie when the request is not HTTPS and
  refuses to act on raw ``token`` / ``access_token`` / ``error``
  query values.
* ``GET /auth/verificado`` exposes the authenticated principal
  view: "identidad verificada; onboarding aún no habilitado".
* ``POST /auth/logout`` clears the local session cookie without
  touching commerce data.

The router never imports a domain service, never calls
``get_session``, never mutates state and never logs credentials,
tokens, callback URLs, full headers or raw identity-provider
errors. ``autoescape`` is enabled in the Jinja environment so any
user-supplied value is HTML-escaped before it lands in the rendered
template.
"""

from __future__ import annotations

import logging
from pathlib import Path as PathLib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from backend.auth import (
    AuthenticatedPrincipal,
    resolve_supabase_auth_settings,
)
from backend.auth.abuse_guard import (
    AbuseGuardUnavailable,
    request_magic_link_authorization,
)
from backend.auth.jwt_validator import JwtValidationError, validate_supabase_jwt
from backend.auth.pkce import (
    PKCE_COOKIE_NAME,
    PkceValidationError,
    build_clear_pkce_cookie_header,
    build_pkce_cookie_header,
    encode_pkce_cookie,
    generate_pkce_pair,
    parse_pkce_cookie,
)
from backend.auth.session import (
    InsecureCookieDeliveryError,
    build_clear_cookie_header,
    build_cookie_header,
    encode_session,
)
from backend.auth.supabase_client import (
    SupabaseAuthError,
    exchange_magic_link_code,
    is_valid_email_shape,
    request_magic_link_otp,
)
from backend.dependencies import try_authenticated_owner_principal
from backend.services.exceptions import InvalidSupabaseAuthConfig

_TEMPLATE_DIR = (
    PathLib(__file__).resolve().parents[1] / "templates" / "public_onboarding"
)

_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
_templates.env.autoescape = True

logger = logging.getLogger(__name__)

router = APIRouter(tags=["public-onboarding"])

_PHASE2_FEATURE_DISABLED_MESSAGE = (
    "El registro por enlace a tu email aún no está disponible."
)
_PHASE2_LINK_REQUEST_SENT_MESSAGE = (
    "Si el email está registrado, vas a recibir un enlace para "
    "continuar. Revisá tu casilla para confirmar."
)
_PHASE2_AUTH_UNAVAILABLE_MESSAGE = (
    "No pudimos verificar tu identidad ahora. Probá de nuevo más tarde."
)
_PHASE2_SIGNIN_REQUIRED_MESSAGE = (
    "Necesitamos verificar tu identidad para continuar. Pedí un "
    "enlace desde la página de inicio."
)
_PHASE2_CONFIG_UNAVAILABLE_MESSAGE = (
    "El servicio de identidad no está disponible en este momento. "
    "Volvé a intentar más tarde."
)


def _is_request_secure(request: Request) -> bool:
    """Return ``True`` when the request was served over HTTPS.

    The helper inspects ``request.url.scheme`` so it works for direct
    connections and for ASGI servers that propagate the original
    scheme. It also honours the ``X-Forwarded-Proto`` header that
    reverse proxies set so the callback can refuse to mint a
    session cookie when the original request reached the proxy
    over plain HTTP.
    """
    if request.url.scheme.lower() == "https":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if isinstance(forwarded_proto, str):
        first = forwarded_proto.split(",")[0].strip().lower()
        if first == "https":
            return True
    return False


def _render_config_unavailable_response(request: Request) -> Response:
    """Render the bounded ``503`` view for a config error.

    The view is shared by every Phase 2 endpoint so the router
    fails closed without leaking the underlying configuration
    detail to the visitor.
    """
    return _templates.TemplateResponse(
        request=request,
        name="comenzar_no_disponible.html",
        context={
            "request": request,
            "message": _PHASE2_CONFIG_UNAVAILABLE_MESSAGE,
        },
        status_code=503,
    )


class _Phase2ShortCircuit:
    """Sentinel returned by :func:`_resolve_phase2_settings` on error.

    The wrapper wraps :func:`resolve_supabase_auth_settings` so the
    four Phase 2 endpoints can surface a bounded ``503`` when the
    configuration is invalid; without the wrapper the original
    exception would propagate to the FastAPI default 500 handler.
    When the sentinel is returned the caller MUST return
    ``response`` directly without touching the rest of the handler.
    """

    __slots__ = ("response",)

    def __init__(self, response: Response) -> None:
        self.response = response


def _resolve_phase2_settings(
    request: Request,
) -> Any | _Phase2ShortCircuit:
    """Resolve Phase 2 settings and short-circuit any config error."""
    try:
        return resolve_supabase_auth_settings()
    except InvalidSupabaseAuthConfig:
        return _Phase2ShortCircuit(
            _render_config_unavailable_response(request)
        )


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing(request: Request) -> HTMLResponse:
    """Render the public landing page for the self-service trial."""
    return _templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "request": request,
            "comenzar_url": "/comenzar",
        },
        status_code=200,
    )


def _render_feature_disabled_form(request: Request) -> HTMLResponse:
    """Render the placeholder form when the feature is disabled.

    The template preserves the documented Phase 1 copy and never
    invites the visitor to submit an email.
    """
    return _templates.TemplateResponse(
        request=request,
        name="proximamente.html",
        context={"request": request},
        status_code=200,
    )


@router.get(
    "/comenzar", response_class=HTMLResponse, include_in_schema=False
)
def comenzar(request: Request) -> Response:
    """Render the email request form.

    When the Supabase feature is disabled the route falls back to
    the Phase 1 placeholder so the landing CTA keeps resolving to a
    stable page. The Phase 2 form is server-rendered with explicit
    labels, focusable controls and a working submit button; the
    handler never imports a domain service and never opens a
    database session.
    """
    settings = _resolve_phase2_settings(request)
    if isinstance(settings, _Phase2ShortCircuit):
        return settings.response
    if not settings.enabled:
        return _render_feature_disabled_form(request)
    return _templates.TemplateResponse(
        request=request,
        name="comenzar.html",
        context={
            "request": request,
            "feature_available": True,
            "error_message": None,
            "submitted_email": "",
        },
        status_code=200,
    )


@router.post(
    "/comenzar", response_class=HTMLResponse, include_in_schema=False
)
async def comenzar_submit(
    request: Request,
    email: str = Form(default=""),
) -> Response:
    """Process the email request and render the neutral confirmation.

    The route enforces the enumeration-safe contract: the rendered
    view is identical for known and unknown addresses; the helper
    never reports which case occurred. When the operator has not
    configured the abuse guard the route refuses to call the
    provider so a missing rate limiter cannot be silently bypassed
    by the application.

    The route also refuses to run when the request is not served
    over HTTPS — the linked Supabase OTP endpoint and the abuse
    guard MUST never be reached over plain HTTP, and the
    ``Set-Cookie`` header MUST never be emitted without the
    ``Secure`` flag. When the request is insecure the route
    short-circuits with the bounded ``503`` view BEFORE generating
    the PKCE pair, contacting the abuse guard or contacting the
    provider; the verifier is therefore never minted, persisted
    or sent.

    The handler mints a fresh server-side PKCE pair before
    issuing the Supabase OTP request, stores the verifier in a
    short-lived signed temp cookie and embeds the matching
    challenge in the request body. The verifier is never
    persisted, logged or rendered.

    The handler never imports a domain service, never opens a
    database session, never logs the email and never renders the
    provider response.
    """
    settings = _resolve_phase2_settings(request)
    if isinstance(settings, _Phase2ShortCircuit):
        return settings.response
    if not settings.enabled:
        return _render_feature_disabled_form(request)

    cleaned_email = email.strip()
    if not is_valid_email_shape(cleaned_email):
        return _templates.TemplateResponse(
            request=request,
            name="comenzar.html",
            context={
                "request": request,
                "feature_available": True,
                "error_message": _PHASE2_LINK_REQUEST_SENT_MESSAGE,
                "submitted_email": "",
            },
            status_code=200,
        )

    request_is_secure = _is_request_secure(request)
    if not request_is_secure:
        logger.info(
            "public_onboarding_link_request_rejected",
            extra={"reason": "insecure_request"},
        )
        return _templates.TemplateResponse(
            request=request,
            name="comenzar_no_disponible.html",
            context={
                "request": request,
                "message": _PHASE2_AUTH_UNAVAILABLE_MESSAGE,
            },
            status_code=503,
        )

    pair = generate_pkce_pair()
    remote_ip = request.client.host if request.client else None

    try:
        guard_decision = request_magic_link_authorization(
            email=cleaned_email,
            settings=settings,
            remote_ip=remote_ip,
        )
    except AbuseGuardUnavailable as exc:
        logger.info(
            "public_onboarding_link_abuse_guard_blocked",
            extra={"reason": exc.reason},
        )
        return _templates.TemplateResponse(
            request=request,
            name="comenzar_no_disponible.html",
            context={
                "request": request,
                "message": _PHASE2_AUTH_UNAVAILABLE_MESSAGE,
            },
            status_code=503,
        )

    if not guard_decision.allowed:
        logger.info("public_onboarding_link_abuse_guard_denied")
        return _templates.TemplateResponse(
            request=request,
            name="comenzar_no_disponible.html",
            context={
                "request": request,
                "message": _PHASE2_AUTH_UNAVAILABLE_MESSAGE,
            },
            status_code=503,
        )

    try:
        request_magic_link_otp(
            email=cleaned_email,
            challenge=pair.challenge,
            settings=settings,
        )
    except SupabaseAuthError as exc:
        logger.info(
            "public_onboarding_link_request_failed",
            extra={"reason": exc.reason},
        )
        return _templates.TemplateResponse(
            request=request,
            name="comenzar_no_disponible.html",
            context={
                "request": request,
                "message": _PHASE2_AUTH_UNAVAILABLE_MESSAGE,
            },
            status_code=503,
        )

    response = _templates.TemplateResponse(
        request=request,
        name="comenzar_enviado.html",
        context={
            "request": request,
            "message": _PHASE2_LINK_REQUEST_SENT_MESSAGE,
        },
        status_code=200,
    )
    response.headers.append(
        "Set-Cookie",
        build_pkce_cookie_header(
            value=encode_pkce_cookie(pair=pair, settings=settings),
            settings=settings,
            request_is_secure=request_is_secure,
        ),
    )
    return response


@router.get(
    "/auth/callback", response_class=HTMLResponse, include_in_schema=False
)
def auth_callback(
    request: Request,
    code: str = "",
) -> Response:
    """Exchange the one-time ``code`` and redirect to the verified view.

    The handler enforces the clean-redirect contract:

    * The handler accepts only the documented ``code`` query
      parameter; it never reads ``token``, ``access_token`` or
      ``error`` query values. Any raw JWT, access token or provider
      error description is rejected without ever being validated.
    * The handler reads the server-issued PKCE temp cookie and
      exchanges the ``code`` for an access JWT through the
      documented Supabase PKCE token endpoint with a bounded
      timeout.
    * The handler validates the resulting JWT through the JWKS
      asymmetric contract (signature, issuer, audience, expiry,
      subject). A failure maps to the bounded sign-in-required
      view without leaking the reason.
    * When validation succeeds the handler sets the local session
      cookie and redirects to ``/auth/verificado``. The redirect
      URL never carries the code, the token, the original query
      string, the error code or any other sensitive value.
    * The handler refuses to mint an authenticated cookie when the
      request was served over plain HTTP — the callback must be
      reached over HTTPS so the signed cookie cannot be observed
      in transit.

    The handler never opens a database session, never logs the
    token, the code or the verifier and never persists any identity
    row.
    """
    settings = _resolve_phase2_settings(request)
    if isinstance(settings, _Phase2ShortCircuit):
        return settings.response
    if not settings.enabled:
        return _render_feature_disabled_form(request)

    request_is_secure = _is_request_secure(request)
    cleaned_code = code.strip()

    if not cleaned_code:
        logger.info(
            "public_onboarding_callback_rejected",
            extra={"reason": "missing_code"},
        )
        return _redirect_to_verified(
            settings, request_is_secure=request_is_secure
        )

    raw_cookie = request.headers.get("cookie")
    cookie_headers: dict[str, str] = (
        {"cookie": raw_cookie} if isinstance(raw_cookie, str) else {}
    )
    try:
        pkce_cookie = parse_pkce_cookie(
            cookie_headers, settings=settings
        )
    except PkceValidationError:
        pkce_cookie = None

    if pkce_cookie is None:
        logger.info(
            "public_onboarding_callback_rejected",
            extra={"reason": "pkce_cookie_missing"},
        )
        return _redirect_to_verified(
            settings, request_is_secure=request_is_secure
        )

    try:
        access_token = exchange_magic_link_code(
            code=cleaned_code,
            code_verifier=pkce_cookie.verifier,
            settings=settings,
        )
    except SupabaseAuthError as exc:
        logger.info(
            "public_onboarding_callback_code_exchange_failed",
            extra={"reason": exc.reason},
        )
        return _redirect_to_verified(
            settings, request_is_secure=request_is_secure
        )

    try:
        principal = validate_supabase_jwt(
            access_token, settings=settings
        )
    except JwtValidationError as exc:
        logger.info(
            "public_onboarding_callback_jwt_invalid",
            extra={"reason": exc.reason},
        )
        return _redirect_to_verified(
            settings, request_is_secure=request_is_secure
        )

    try:
        cookie_value = build_cookie_header(
            value=encode_session(principal, settings=settings),
            settings=settings,
            request_is_secure=request_is_secure,
        )
    except InsecureCookieDeliveryError:
        logger.info(
            "public_onboarding_callback_rejected",
            extra={"reason": "insecure_request"},
        )
        return _redirect_to_verified(
            settings, request_is_secure=request_is_secure
        )

    response = RedirectResponse(
        url="/auth/verificado",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.headers.append("Set-Cookie", cookie_value)
    response.headers.append(
        "Set-Cookie",
        build_clear_pkce_cookie_header(
            request_is_secure=request_is_secure
        ),
    )
    return response


def _redirect_to_verified(
    settings: Any, *, request_is_secure: bool
) -> Response:
    """Redirect to the bounded verified view.

    The helper centralises the failure redirect so the callback
    can never leak the token, the original query string or the
    provider error description. The redirect target is the
    verified view; the view itself raises the sign-in-required
    outcome when the cookie is absent.
    """
    response = RedirectResponse(
        url="/auth/verificado",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.headers.append(
        "Set-Cookie",
        build_clear_pkce_cookie_header(
            request_is_secure=request_is_secure
        ),
    )
    return response


@router.get(
    "/auth/verificado",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def auth_verificado(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal | None,
        Depends(try_authenticated_owner_principal),
    ],
) -> Response:
    """Render the bounded verified principal view.

    The view is the only authenticated surface Phase 2 exposes.
    It intentionally displays the "identidad verificada; onboarding
    aún no habilitado" copy and never claims that the visitor can
    configure a commerce, accept orders or perform any operational
    action.

    When the dependency returns ``None`` (missing cookie, expired
    cookie, feature disabled, configuration error) the route
    renders the bounded sign-in-required view so a visitor can
    recover without leaking the underlying reason.
    """
    settings = _resolve_phase2_settings(request)
    if isinstance(settings, _Phase2ShortCircuit):
        return settings.response
    if not settings.enabled:
        return _render_feature_disabled_form(request)
    if principal is None:
        return _templates.TemplateResponse(
            request=request,
            name="auth_no_autenticado.html",
            context={
                "request": request,
                "message": _PHASE2_SIGNIN_REQUIRED_MESSAGE,
            },
            status_code=401,
        )
    return _templates.TemplateResponse(
        request=request,
        name="identidad_verificada.html",
        context={
            "request": request,
            "subject": principal.subject,
            "logout_url": "/auth/logout",
        },
        status_code=200,
    )


@router.post(
    "/auth/logout", response_class=HTMLResponse, include_in_schema=False
)
def auth_logout(request: Request) -> Response:
    """Clear the local session cookie and redirect to the landing.

    The handler always succeeds: an absent cookie is a no-op. The
    response sets the documented cookie flags with ``Max-Age=0`` so
    the browser removes the cookie regardless of its remaining
    lifetime. The handler never opens a database session and never
    calls the provider logout endpoint.
    """
    settings = _resolve_phase2_settings(request)
    request_is_secure = _is_request_secure(request)
    response = RedirectResponse(
        url="/comenzar",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    if not isinstance(settings, _Phase2ShortCircuit):
        response.headers.append(
            "Set-Cookie",
            build_clear_cookie_header(
                request_is_secure=request_is_secure
            ),
        )
        response.headers.append(
            "Set-Cookie",
            build_clear_pkce_cookie_header(
                request_is_secure=request_is_secure
            ),
        )
    return response


__all__ = ["PKCE_COOKIE_NAME", "router"]