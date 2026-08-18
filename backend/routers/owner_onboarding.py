"""Phase 3 / Phase 4A owner onboarding wizard surface.

This router is the only authenticated route exposed by the
``add-commerce-self-service-onboarding`` change. It implements
the narrow Phase 3 contract plus the Phase 4A completion
seam:

* the route requires the Phase 2 authenticated principal
  (validated Supabase JWT -> local session cookie);
* the route resolves or creates the durable :class:`CuentaUsuario`
  row for the principal's immutable external subject;
* the route loads or creates the single
  :class:`BorradorOnboardingComercio` row owned by that account;
* the route is the only surface that reads or writes that draft;
* the route never accepts a ``comercio_id`` (or any commerce
  resource selector) at the wizard form;
* ``POST /onboarding`` is the only state-changing wizard save; it
  is protected by ``require_same_origin_owner_onboarding_form``
  so a cross-site attacker cannot forge a save;
* the save uses the optimistic-concurrency ``version`` so two
  parallel tabs cannot silently overwrite each other;
* ``POST /onboarding/completar`` is the Phase 4A atomic completion
  transaction. It is protected by the same dependency, accepts
  only the path-bound nonce and the authenticated principal, and
  delegates every commerce validation to the shared
  :meth:`ComercioService.stage_create` seam before staging the
  closed ``OWNER`` membership and the terminal draft
  transition. The router owns the single commit / rollback
  boundary so any persistence failure rolls the whole transaction
  back together.

The router imports ``Comercio`` for the canonical constants
``ComercioService.stage_create`` reads from the staged ``Comercio``
row, and ``ComercioService`` is used exclusively through its
shared, non-committing authoring seam — the Admin
commit-bound :meth:`ComercioService.create` is never called from
onboarding.
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
    DraftTerminalError,
)
from backend.repositories.comercio_usuario_repository import (
    ComercioUsuarioRepository,
)
from backend.services.exceptions import DuplicateSlug, DuplicateWhatsapp
from backend.services.owner_onboarding_completion_service import (
    CompletionOutcome,
    OwnerOnboardingCompletionError,
    OwnerOnboardingInactivoMissing,
    OwnerOnboardingIncomplete,
    OwnerOnboardingNoDraft,
    OwnerOnboardingTerminalInconsistent,
    OwnerOnboardingUnicityRace,
    complete_onboarding,
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

_COMPLETION_PATH = "/onboarding/completar"

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


def _form_nonce(request: Request, *, path: str) -> str:
    """Return the path-bound CSRF nonce for the wizard surface."""
    return compute_owner_onboarding_form_nonce(
        path=path,
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


def _draft_terminal(draft: Any) -> bool:
    """Return ``True`` iff the wizard draft is in the terminal state."""
    return (
        getattr(draft, "comercio_id", None) is not None
        and getattr(draft, "completado_en", None) is not None
    )


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
        "form_nonce": _form_nonce(request, path="/onboarding"),
        "completion_form_nonce": _form_nonce(
            request, path=_COMPLETION_PATH
        ),
        "form_nonce_field": OWNER_FORM_NONCE_FIELD,
        "field_values": field_values,
        "progress": progress,
        "error": _danger(error) if error else "",
        "success": success,
        "phase_label": "Fase 4A · borrador y activación del comercio",
    }
    return _templates.TemplateResponse(
        request=request,
        name="onboarding.html",
        context=context,
        status_code=200,
    )


def _render_terminal(
    request: Request,
    *,
    cuenta_id: int,
    subject: str,
    draft: Any,
    slug: str,
    outcome: CompletionOutcome,
    just_completed: bool,
) -> HTMLResponse:
    """Render the bounded terminal view without an editable form."""
    context: dict[str, object] = {
        "request": request,
        "subject": subject,
        "cuenta_id": cuenta_id,
        "draft_id": int(draft.id),
        "version": int(draft.version),
        "comercio_id": outcome.comercio_id,
        "slug": slug,
        "completado_en_iso": outcome.completado_en.isoformat(),
        "just_completed": just_completed,
        "phase_label": "Fase 4A · registro completo",
    }
    return _templates.TemplateResponse(
        request=request,
        name="onboarding_completado.html",
        context=context,
        status_code=200,
    )


def _resolve_completion_outcome(
    request: Request,
    session: Session,
    principal: AuthenticatedPrincipal,
) -> tuple[Any, CompletionOutcome, str]:
    """Run the completion transaction and resolve its outcome.

    The helper is intentionally narrow: it stages the commerce,
    the membership and the terminal draft transition inside the
    caller-owned ``with session.begin():`` block and returns the
    rendered terminal tuple on success. It does NOT translate
    exceptions, catch any errors, or build HTML responses: the
    :class:`OwnerOnboardingCompletionError` (and its typed
    subclasses) raised by :func:`complete_onboarding` MUST
    escape the helper so the ``with session.begin():`` context
    manager can roll the staged commerce, membership and draft
    transition back together. The outer route handler is the
    only surface that maps the typed failure to a bounded HTML
    response, after the transaction is closed.
    """
    outcome = complete_onboarding(session, principal)

    from backend.models.borrador_onboarding_comercio import (
        BorradorOnboardingComercio,
    )

    draft = session.get(BorradorOnboardingComercio, outcome.draft_id)
    if draft is None:
        raise OwnerOnboardingError(
            f"draft {outcome.draft_id} disappeared from the completion "
            "transaction before the route could render the terminal view"
        )
    slug_value = getattr(draft, "slug", "") or ""
    return draft, outcome, str(slug_value)


def _completion_required_fields_error(
    request: Request,
) -> HTMLResponse:
    return _service_unavailable_response(
        request,
        "Tu borrador todavía no está completo; volvé al wizard y "
        "completá los datos antes de crear el comercio.",
    )


def _completion_no_draft_error(
    request: Request,
) -> HTMLResponse:
    return _service_unavailable_response(
        request,
        "No encontramos tu borrador; volvé al wizard para crearlo.",
    )


def _completion_inactivo_missing_error(
    request: Request,
) -> HTMLResponse:
    return _service_unavailable_response(
        request,
        "No podemos crear tu comercio ahora: falta configurar el "
        "estado INACTIVO. Pedinos que lo revisemos.",
    )


def _completion_inactive_account_error(
    request: Request,
) -> HTMLResponse:
    return _service_unavailable_response(
        request,
        "Tu cuenta está desactivada; contactanos para reactivarla.",
    )


def _completion_terminal_inconsistent_error(
    request: Request,
) -> HTMLResponse:
    return _service_unavailable_response(
        request,
        "Tu registro está en un estado inconsistente; contactanos "
        "para revisarlo. No creamos un segundo comercio.",
    )


def _completion_unicity_race_error(
    request: Request,
) -> HTMLResponse:
    return _service_unavailable_response(
        request,
        "No pudimos crear tu comercio porque el identificador "
        "o WhatsApp ya está en uso. Vuelve al wizard y elegí "
        "otro valor antes de continuar.",
    )


def _completion_duplicate_slug_error(
    request: Request,
) -> HTMLResponse:
    return _service_unavailable_response(
        request,
        "Ya existe un comercio con ese identificador; volvé al "
        "wizard y elegí otro slug antes de continuar.",
    )


def _completion_duplicate_whatsapp_error(
    request: Request,
) -> HTMLResponse:
    return _service_unavailable_response(
        request,
        "Ya existe un comercio con ese WhatsApp; contactanos si "
        "necesitás ayuda.",
    )


def _completion_generic_error(
    request: Request,
) -> HTMLResponse:
    return _service_unavailable_response(
        request,
        "No pudimos completar tu registro ahora; volvé a intentarlo.",
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

    if _draft_terminal(draft):
        slug_value = getattr(draft, "slug", "") or ""
        comercio_id_value = draft.comercio_id
        completado_en_value = draft.completado_en
        assert comercio_id_value is not None
        assert completado_en_value is not None
        # A terminal draft is only authoritative when an active
        # OWNER membership links the resolved account to the
        # referenced comercio. The membership lookup is the
        # documented "fail closed" signal when the terminal row
        # exists but no active membership, or the membership
        # belongs to another account: the wizard must NOT expose
        # the comercio / slug / id and must instead render a
        # bounded feedback view so the visitor cannot infer any
        # commerce from the terminal state.
        membership_repo = ComercioUsuarioRepository(session)
        owner_membership = membership_repo.get_owner_membership(
            cuenta_usuario_id=int(cuenta.id),
            comercio_id=int(comercio_id_value),
        )
        if (
            owner_membership is None
            or not bool(getattr(owner_membership, "activo", False))
        ):
            logger.error(
                "owner_onboarding_terminal_draft_inconsistent_get",
                extra={
                    "reason": (
                        "missing_or_inactive_owner_membership"
                    ),
                    "draft_id": int(draft.id),
                    "comercio_id": int(comercio_id_value),
                },
            )
            return _service_unavailable_response(
                request,
                "Tu registro está en un estado inconsistente; "
                "contactanos para revisarlo. No expusimos tu "
                "comercio.",
            )
        outcome = CompletionOutcome(
            cuenta_id=int(cuenta.id),
            draft_id=int(draft.id),
            comercio_id=int(comercio_id_value),
            completado_en=completado_en_value,
        )
        return _render_terminal(
            request,
            cuenta_id=int(cuenta.id),
            subject=principal.subject,
            draft=draft,
            slug=str(slug_value),
            outcome=outcome,
            just_completed=False,
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
    slug: str = Form(""),
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

    if _draft_terminal(draft):
        return _service_unavailable_response(
            request,
            "Tu registro ya está completo; no aceptamos cambios sobre "
            "el borrador terminal.",
        )

    fields: dict[str, str] = {
        "nombre_fantasia": nombre_fantasia,
        "nombre_corto": nombre_corto,
        "razon_social": razon_social,
        "cuit": cuit,
        "whatsapp": whatsapp,
        "slug": slug,
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
    except DraftTerminalError:
        return _service_unavailable_response(
            request,
            "Tu registro ya está completo; no aceptamos cambios sobre "
            "el borrador terminal.",
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


@router.post(
    _COMPLETION_PATH,
    response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(require_same_origin_owner_onboarding_form)],
)
def onboarding_completar_post(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_authenticated_owner_principal),
    ],
    session: Annotated[Session, Depends(get_session)],
    nonce: str = Form(""),
) -> Response:
    """Atomically stage the Phase 4A completion transaction.

    The route is the only surface that triggers the completion
    transaction. It owns the single caller-owned ``session``
    block so any persistence failure rolls the staged commerce,
    the staged membership and the staged terminal draft
    transition back together. The route refuses to read a
    ``comercio_id`` or any second copy of the commerce payload —
    the completion service uses the persisted, authenticated draft
    and the canonical ``INACTIVO`` lifecycle state exclusively.

    The route accepts a single optional ``nonce`` form field
    so FastAPI registers the body as a multipart / url-encoded
    form. The ``nonce`` has already been validated by the
    ``require_same_origin_owner_onboarding_form`` dependency
    using the path-bound nonce and is therefore not re-checked
    here. No additional form parameters are accepted: a
    ``comercio_id`` or any second commerce payload is silently
    ignored because the route never reads the form values
    beyond the path-bound nonce.

    The route resolves the application account (and only the
    account) BEFORE opening ``session.begin()``. The Phase 3
    helper :func:`resolve_or_create_cuenta` may call
    ``session.commit()`` when a brand-new ``CuentaUsuario`` row
    has to be inserted; running it inside the completion
    transaction would prematurely close the surrounding unit-
    of-work and let the completion helper observe a half-
    committed state. The completion transaction therefore spans
    exclusively the ``Comercio`` insert, the ``ComercioUsuario``
    insert and the terminal draft transition.
    """
    # Resolve the account row OUTSIDE ``session.begin()``.
    # ``resolve_or_create_cuenta`` is the documented Phase 3
    # helper and may commit a brand-new ``CuentaUsuario`` row.
    # Committing inside the completion transaction would close
    # the surrounding unit-of-work prematurely and surface as
    # an unexpected 500 / nested transaction error. The legacy
    # contract is preserved because the helper still owns its
    # own commit boundary.
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

    # Capture the resolved account id BEFORE any state reset:
    # ``resolve_or_create_cuenta`` may leave the session in an
    # autobegun read-only transaction (the ``SELECT`` it issues
    # to look up the subject). The completion transaction MUST
    # start a fresh unit-of-work so the staged commerce /
    # membership / terminal draft transition share the same
    # commit / rollback boundary. The legacy helper already
    # committed anything it staged, so the rollback below is a
    # no-op for the account row but releases the autobegun
    # transaction so the explicit ``with session.begin():``
    # block can open.
    cuenta_id = int(cuenta.id)
    session.rollback()

    # The completion transaction is the single unit-of-work that
    # the route owns. The helpers inside ``with session.begin():``
    # (``_resolve_completion_outcome`` + ``complete_onboarding``)
    # never catch typed exceptions and never build HTML responses:
    # every :class:`OwnerOnboardingCompletionError` (and its typed
    # subclasses) raised by those helpers ESCAPES the ``with``
    # block so the context manager performs the rollback before
    # the outer handler translates the typed failure to a bounded
    # service-unavailable view. The owner never sees a raw 500 and
    # the route never continues using a session left in the failed
    # state SQLAlchemy enters after an ``IntegrityError``.
    draft: Any | None = None
    outcome: CompletionOutcome | None = None
    slug_value: str = ""
    try:
        with session.begin():
            resolved = _resolve_completion_outcome(
                request, session, principal
            )
            draft, outcome, slug_value = resolved
    except OwnerAccountInactive:
        logger.info(
            "owner_onboarding_completion_account_inactive",
            extra={"reason": "OwnerAccountInactive"},
        )
        return _completion_inactive_account_error(request)
    except OwnerOnboardingInactivoMissing:
        logger.error(
            "owner_onboarding_inactivo_missing",
            extra={"reason": "OwnerOnboardingInactivoMissing"},
        )
        return _completion_inactivo_missing_error(request)
    except OwnerOnboardingIncomplete:
        logger.info(
            "owner_onboarding_incomplete",
            extra={"reason": "OwnerOnboardingIncomplete"},
        )
        return _completion_required_fields_error(request)
    except OwnerOnboardingNoDraft:
        logger.info(
            "owner_onboarding_no_draft",
            extra={"reason": "OwnerOnboardingNoDraft"},
        )
        return _completion_no_draft_error(request)
    except OwnerOnboardingTerminalInconsistent:
        logger.error(
            "owner_onboarding_terminal_inconsistent",
            extra={"reason": "OwnerOnboardingTerminalInconsistent"},
        )
        return _completion_terminal_inconsistent_error(request)
    except OwnerOnboardingUnicityRace:
        logger.error(
            "owner_onboarding_unicity_race",
            extra={"reason": "OwnerOnboardingUnicityRace"},
        )
        # The ``with session.begin():`` context manager already
        # rolled the staged commerce, membership and draft
        # transition back together; the session is closed by the
        # router-managed dependency. We render a bounded
        # service-unavailable view so the visitor never sees a
        # raw 500 and we never continue using the failed session.
        return _completion_unicity_race_error(request)
    except DuplicateSlug:
        logger.info(
            "owner_onboarding_completion_duplicate_slug",
            extra={"reason": "DuplicateSlug"},
        )
        return _completion_duplicate_slug_error(request)
    except DuplicateWhatsapp:
        logger.info(
            "owner_onboarding_completion_duplicate_whatsapp",
            extra={"reason": "DuplicateWhatsapp"},
        )
        return _completion_duplicate_whatsapp_error(request)
    except (OwnerOnboardingCompletionError, OwnerOnboardingError) as exc:
        logger.info(
            "owner_onboarding_completion_failed",
            extra={"reason": type(exc).__name__},
        )
        return _completion_generic_error(request)

    assert draft is not None
    assert outcome is not None
    return _render_terminal(
        request,
        cuenta_id=cuenta_id,
        subject=principal.subject,
        draft=draft,
        slug=slug_value,
        outcome=outcome,
        just_completed=True,
    )


__all__ = ["router"]
