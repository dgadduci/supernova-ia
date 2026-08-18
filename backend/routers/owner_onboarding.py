"""Phase 3 owner onboarding wizard surface.

This router is the only authenticated route exposed by the
``add-commerce-self-service-onboarding`` change. It implements the
narrow Phase 3 contract:

* the route requires the Phase 2 authenticated principal
  (validated Supabase JWT -> local session cookie);
* the route resolves or creates the durable :class:`CuentaUsuario`
  row for the principal's immutable external subject;
* the route loads or creates the single
  :class:`BorradorOnboardingComercio` row owned by that account;
* the route is the only surface that reads or writes that draft;
* the route never accepts a ``comercio_id`` (or any commerce
  resource selector);
* ``POST /onboarding`` is the only state-changing action; it is
  protected by ``require_same_origin_owner_onboarding_form`` so a
  cross-site attacker cannot forge a save;
* the save uses the optimistic-concurrency ``version`` so two
  parallel tabs cannot silently overwrite each other.

The router imports ``Comercio``, ``ComercioService``,
``ComercioMedioPagoService``, ``MetodosEntregaService``,
``CommerceAvailabilityService`` or any commerce read / write
helper. Creating or mutating a ``Comercio`` row is the
Phase 4 completion transaction's job; the wizard only stages the
basic fields it needs.
"""

from __future__ import annotations

import logging
from pathlib import Path as PathLib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.auth.principal import AuthenticatedPrincipal
from backend.dependencies import (
    OWNER_FORM_NONCE_FIELD,
    _resolve_owner_onboarding_csrf_secret,
    compute_owner_onboarding_form_nonce,
    get_session,
    require_authenticated_owner_principal,
    require_same_origin_owner_onboarding_form,
)
from backend.repositories.borrador_onboarding_comercio_repository import (
    REQUIRED_BASIC_FIELDS,
    DraftConcurrencyError,
)
from backend.services.owner_onboarding_service import (
    OwnerAccountInactive,
    OwnerOnboardingError,
    load_or_create_borrador,
    resolve_or_create_cuenta,
    save_borrador,
)

_TEMPLATE_DIR = (
    PathLib(__file__).resolve().parents[1]
    / "templates"
    / "owner_onboarding"
)

_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
_templates.env.autoescape = True

logger = logging.getLogger(__name__)

router = APIRouter(tags=["owner-onboarding"])

_FORM_FIELDS: tuple[str, ...] = REQUIRED_BASIC_FIELDS + (
    "piso_departamento",
    "codigo_postal",
)


def _service_unavailable_response(
    request: Request, message: str
) -> HTMLResponse:
    """Render the bounded ``503`` view for a service outage."""
    return _templates.TemplateResponse(
        request=request,
        name="onboarding_no_disponible.html",
        context={"request": request, "message": message},
        status_code=503,
    )


def _danger(message: str) -> str:
    """Escape ``message`` so it can be embedded in the rendered HTML."""
    return (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape(value: Any) -> str:
    """Render ``value`` safely for the pre-filled field values."""
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _form_nonce(request: Request) -> str:
    """Return the path-bound CSRF nonce for the wizard."""
    return compute_owner_onboarding_form_nonce(
        path=request.url.path,
        secret=_resolve_owner_onboarding_csrf_secret(),
    )


def _draft_progress(draft: Any) -> dict[str, object]:
    """Return a server-derived progress view for the wizard."""
    completed = 0
    pending: list[str] = []
    for name in REQUIRED_BASIC_FIELDS:
        value = getattr(draft, name, None)
        if isinstance(value, str) and value.strip():
            completed += 1
        else:
            pending.append(name)
    return {
        "completed": completed,
        "total": len(REQUIRED_BASIC_FIELDS),
        "pending": pending,
        "completo": bool(getattr(draft, "completo", False)),
    }


def _render_wizard(
    request: Request,
    *,
    cuenta_id: int,
    subject: str,
    draft: Any,
    error: str | None = None,
    success: bool = False,
) -> HTMLResponse:
    """Render the wizard with the current draft and status."""
    field_values: dict[str, str] = {
        name: _escape(getattr(draft, name, None))
        for name in _FORM_FIELDS
    }
    progress = _draft_progress(draft)
    context: dict[str, object] = {
        "request": request,
        "subject": subject,
        "cuenta_id": cuenta_id,
        "draft_id": int(draft.id),
        "version": int(draft.version),
        "form_nonce": _form_nonce(request),
        "form_nonce_field": OWNER_FORM_NONCE_FIELD,
        "field_values": field_values,
        "progress": progress,
        "error": _danger(error) if error else "",
        "success": success,
        "phase_label": "Fase 3 · borrador del comercio",
    }
    return _templates.TemplateResponse(
        request=request,
        name="onboarding.html",
        context=context,
        status_code=200,
    )


@router.get(
    "/onboarding",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def onboarding_get(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_authenticated_owner_principal),
    ],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Render the wizard for the authenticated principal."""
    try:
        cuenta = resolve_or_create_cuenta(session, principal)
    except OwnerAccountInactive:
        return _service_unavailable_response(
            request,
            "Tu cuenta está desactivada; contactanos para reactivarla.",
        )
    except OwnerOnboardingError as exc:
        logger.info(
            "owner_onboarding_resolve_failed",
            extra={"reason": type(exc).__name__},
        )
        return _service_unavailable_response(
            request, "El servicio no puede resolver tu cuenta ahora."
        )

    try:
        draft = load_or_create_borrador(session, cuenta)
    except OwnerAccountInactive:
        return _service_unavailable_response(
            request,
            "Tu cuenta está desactivada; contactanos para reactivarla.",
        )
    except OwnerOnboardingError as exc:
        logger.info(
            "owner_onboarding_draft_load_failed",
            extra={"reason": type(exc).__name__},
        )
        return _service_unavailable_response(
            request, "No pudimos cargar tu borrador ahora."
        )

    return _render_wizard(
        request,
        cuenta_id=cuenta.id,
        subject=principal.subject,
        draft=draft,
        error=None,
        success=False,
    )


@router.post(
    "/onboarding",
    response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(require_same_origin_owner_onboarding_form)],
)
async def onboarding_post(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_authenticated_owner_principal),
    ],
    session: Annotated[Session, Depends(get_session)],
    expected_version: int = Form(...),
    nombre_fantasia: str = Form(""),
    nombre_corto: str = Form(""),
    razon_social: str = Form(""),
    cuit: str = Form(""),
    whatsapp: str = Form(""),
    calle: str = Form(""),
    numero: str = Form(""),
    piso_departamento: str = Form(""),
    localidad: str = Form(""),
    provincia: str = Form(""),
    codigo_postal: str = Form(""),
) -> Response:
    """Persist the form payload with the optimistic version check."""
    try:
        cuenta = resolve_or_create_cuenta(session, principal)
    except OwnerAccountInactive:
        return _service_unavailable_response(
            request,
            "Tu cuenta está desactivada; contactanos para reactivarla.",
        )
    except OwnerOnboardingError as exc:
        logger.info(
            "owner_onboarding_resolve_failed",
            extra={"reason": type(exc).__name__},
        )
        return _service_unavailable_response(
            request, "El servicio no puede resolver tu cuenta ahora."
        )

    try:
        draft = load_or_create_borrador(session, cuenta)
    except OwnerAccountInactive:
        return _service_unavailable_response(
            request,
            "Tu cuenta está desactivada; contactanos para reactivarla.",
        )
    except OwnerOnboardingError as exc:
        logger.info(
            "owner_onboarding_draft_load_failed",
            extra={"reason": type(exc).__name__},
        )
        return _service_unavailable_response(
            request, "No pudimos cargar tu borrador ahora."
        )

    fields: dict[str, str] = {
        "nombre_fantasia": nombre_fantasia,
        "nombre_corto": nombre_corto,
        "razon_social": razon_social,
        "cuit": cuit,
        "whatsapp": whatsapp,
        "calle": calle,
        "numero": numero,
        "piso_departamento": piso_departamento,
        "localidad": localidad,
        "provincia": provincia,
        "codigo_postal": codigo_postal,
    }

    try:
        saved = save_borrador(
            session,
            draft,
            expected_version=expected_version,
            fields=fields,
        )
    except DraftConcurrencyError:
        fresh = load_or_create_borrador(session, cuenta)
        return _render_wizard(
            request,
            cuenta_id=cuenta.id,
            subject=principal.subject,
            draft=fresh,
            error=(
                "Tu borrador cambió desde la última vez que lo abriste. "
                "Revisá los valores guardados y guardá de nuevo."
            ),
        )
    except OwnerOnboardingError as exc:
        logger.info(
            "owner_onboarding_save_failed",
            extra={"reason": type(exc).__name__},
        )
        return _service_unavailable_response(
            request, "No pudimos guardar tu borrador ahora."
        )

    if request.headers.get("x-onboarding-follow-redirect") == "1":
        redirect = RedirectResponse(
            url="/onboarding", status_code=status.HTTP_303_SEE_OTHER
        )
        return redirect
    return _render_wizard(
        request,
        cuenta_id=cuenta.id,
        subject=principal.subject,
        draft=saved,
        success=True,
    )


__all__ = ["router"]
