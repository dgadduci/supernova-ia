"""Browser-oriented administrative panel routes.

The router is mounted under ``/admin/catalog`` and exposes the
list / detail / flavor-assignment / catalog-create endpoints the
OpenSpec change authorises. Every mutation flows through the shared
:class:`CatalogCreateService` so the JSON API contract, the commit /
rollback sequence and the post-create embedding synchronization are
preserved verbatim.

The router is intentionally NOT a parallel application pipeline. It
never opens a database transaction of its own, never imports the
document builder internals, never calls the embedding provider, never
imports the recognizer pipeline and never logs the credential. The
existing ``get_session`` dependency owns the transaction boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path as PathLib
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Path, Request
from fastapi.params import Form as FormParam
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.admin.forms import (
    CatalogFormError,
    FlavorAssignForm,
)
from backend.admin.view_service import AdministrativeCatalogPanelViewService
from backend.admin.views import (
    PanelFormStatus,
    parse_positive_int,
)
from backend.config.settings import load_settings
from backend.dependencies import (
    PANEL_FORM_NONCE_FIELD,
    compute_panel_form_nonce,
    get_session,
    require_admin_browser_basic,
    require_same_origin_panel_form,
    resolve_panel_csrf_secret,
)
from backend.services.catalog_create_service import CatalogCreateService
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    DuplicatePrecio,
    DuplicatePresentacionCodigo,
    DuplicatePresentacionDescripcion,
    DuplicateProductoNombre,
    FlavorComunicacionInactivo,
    FlavorComunicacionNotFound,
    InvalidCategoriaProducto,
    InvalidPrecio,
    InvalidPresentacion,
    InvalidProducto,
    PrecioNotFound,
    PresentacionNotFound,
    ProductoNotFound,
    ProductoPresentacionNotFound,
)

_TEMPLATE_DIR = (
    PathLib(__file__).resolve().parents[1]
    / "templates"
    / "admin_catalog_panel"
)

_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
_templates.env.autoescape = True

router = APIRouter(
    prefix="/admin/catalog",
    tags=["admin-catalog-panel"],
    dependencies=[
        Depends(require_admin_browser_basic),
        Depends(require_same_origin_panel_form),
    ],
)


def _view_service(
    session: Annotated[Session, Depends(get_session)],
) -> AdministrativeCatalogPanelViewService:
    return AdministrativeCatalogPanelViewService(session)


def _create_service(
    session: Annotated[Session, Depends(get_session)],
) -> CatalogCreateService:
    settings = load_settings()
    return CatalogCreateService(session=session, settings=settings)


def _render(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    return _templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
        status_code=status_code,
    )


def _form_nonce(path: str) -> str:
    return compute_panel_form_nonce(
        path=path, secret=resolve_panel_csrf_secret()
    )


def _form_context(
    *,
    request: Request,
    path: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "request": request,
        "csrf_nonce_field": PANEL_FORM_NONCE_FIELD,
        "form_nonce": _form_nonce(path),
    }
    if extra:
        base.update(extra)
    return base


def _form_error_response(
    *,
    request: Request,
    template_name: str,
    status: PanelFormStatus,
    context_extra: dict[str, Any] | None = None,
    form_path: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render a form that preserves the context after a domain failure.

    The status carries only the bounded, escaped human-readable
    message; the raw exception is never propagated to the
    template. The form's CSRF nonce is regenerated for the
    re-rendered form so the next submission can succeed without
    requiring a fresh navigation. The ``status_code`` defaults to
    ``200``; callers pass a documented HTTP status when the
    failure is a ``404`` (recurso inexistente) or ``409`` (conflicto
    de unicidad) so the response code matches the error semantics.
    """
    context = _form_context(
        request=request,
        path=form_path or str(request.url.path),
        extra={"status": status, **(context_extra or {})},
    )
    return _render(
        request,
        template_name,
        context,
        status_code=status_code,
    )


def _form_success_redirect(target: str) -> RedirectResponse:
    return RedirectResponse(url=target, status_code=303)


def _parse_decimal(raw_value: str | None) -> Decimal:
    if raw_value is None:
        raise ValueError("precio must not be empty")
    cleaned = raw_value.strip().replace(",", ".")
    if not cleaned:
        raise ValueError("precio must not be empty")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("precio must be a non-negative number") from exc


def _coerce_optional_bool(raw_value: str | None) -> bool | None:
    if raw_value is None:
        return None
    cleaned = raw_value.strip().lower()
    if cleaned == "":
        return None
    if cleaned in {"true", "1", "on", "yes", "si", "sí"}:
        return True
    if cleaned in {"false", "0", "off", "no"}:
        return False
    raise ValueError("boolean field must be true, false or empty")


def _coerce_optional_int(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    cleaned = raw_value.strip()
    if cleaned == "":
        return None
    try:
        return int(cleaned)
    except ValueError as exc:
        raise ValueError("integer field must be a non-negative integer") from exc


@dataclass(frozen=True)
class _DomainMapping:
    exception: type[Exception]
    status_code: int
    message: str
    render_form: bool


_NOT_FOUND_RENDER_FORM = True
_VALIDATION_RENDER_FORM = True

_DOMAIN_MAPPING: dict[type[Exception], _DomainMapping] = {
    ComercioNotFound: _DomainMapping(
        ComercioNotFound,
        404,
        "El comercio solicitado no existe.",
        render_form=False,
    ),
    CategoriaProductoNotFound: _DomainMapping(
        CategoriaProductoNotFound,
        404,
        "La categoría solicitada no existe.",
        render_form=False,
    ),
    ProductoNotFound: _DomainMapping(
        ProductoNotFound,
        404,
        "El producto solicitado no existe.",
        render_form=False,
    ),
    PresentacionNotFound: _DomainMapping(
        PresentacionNotFound,
        404,
        "La presentación solicitada no existe.",
        render_form=False,
    ),
    ProductoPresentacionNotFound: _DomainMapping(
        ProductoPresentacionNotFound,
        404,
        "La combinación producto-presentación no existe.",
        render_form=False,
    ),
    PrecioNotFound: _DomainMapping(
        PrecioNotFound,
        404,
        "El precio solicitado no existe.",
        render_form=False,
    ),
    InvalidCategoriaProducto: _DomainMapping(
        InvalidCategoriaProducto,
        400,
        "La categoría enviada no es válida.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
    InvalidProducto: _DomainMapping(
        InvalidProducto,
        400,
        "El producto enviado no es válido.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
    InvalidPresentacion: _DomainMapping(
        InvalidPresentacion,
        400,
        "La presentación enviada no es válida.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
    InvalidPrecio: _DomainMapping(
        InvalidPrecio,
        400,
        "El precio enviado no es válido.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
    DuplicateProductoNombre: _DomainMapping(
        DuplicateProductoNombre,
        409,
        "Ya existe un producto con ese nombre en la categoría seleccionada.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
    DuplicatePresentacionCodigo: _DomainMapping(
        DuplicatePresentacionCodigo,
        409,
        "Ya existe una presentación con ese código en el comercio seleccionado.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
    DuplicatePresentacionDescripcion: _DomainMapping(
        DuplicatePresentacionDescripcion,
        409,
        "Ya existe una presentación con esa descripción en el comercio seleccionado.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
    DuplicatePrecio: _DomainMapping(
        DuplicatePrecio,
        409,
        "La combinación producto-presentación ya tiene un precio cargado.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
    FlavorComunicacionNotFound: _DomainMapping(
        FlavorComunicacionNotFound,
        400,
        "El flavor seleccionado no existe.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
    FlavorComunicacionInactivo: _DomainMapping(
        FlavorComunicacionInactivo,
        400,
        "El flavor seleccionado está inactivo.",
        render_form=_VALIDATION_RENDER_FORM,
    ),
}


def _map_domain_exception(exc: Exception) -> _DomainMapping:
    """Translate a domain exception into a bounded ``_DomainMapping``.

    The mapper returns a generic ``400`` mapping for any exception
    that is not part of the documented domain vocabulary so the
    panel never propagates a raw exception to the operator. The
    generic mapping uses a sanitized message that does not echo
    identifiers, secrets, prompts, exception text or session
    metadata.
    """
    for exc_type, mapping in _DOMAIN_MAPPING.items():
        if isinstance(exc, exc_type):
            return mapping
    return _DomainMapping(
        type(exc),
        400,
        "La operación no pudo completarse. Revisá los valores e intentá nuevamente.",
        render_form=_VALIDATION_RENDER_FORM,
    )


@router.get("/comercios", response_class=HTMLResponse)
def list_comercios(
    request: Request,
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
) -> Response:
    rows = service.list_comercios()
    return _render(
        request,
        "comercios_list.html",
        _form_context(
            request=request,
            path="/admin/catalog/comercios",
            extra={"comercios": rows},
        ),
    )


@router.get("/comercios/{comercio_id}", response_class=HTMLResponse)
def detail_comercio(
    request: Request,
    comercio_id: Annotated[str, Path()],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "comercio_id must be a positive integer"},
            ),
            status_code=400,
        )

    detail = service.get_commerce_detail(parsed_comercio_id)
    if detail is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": comercio_id,
                    "resource_label": "comercio",
                },
            ),
            status_code=404,
        )

    catalog = service.get_commerce_catalog_navigation(parsed_comercio_id)
    if catalog is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": comercio_id,
                    "resource_label": "comercio",
                },
            ),
            status_code=404,
        )

    flavor_options = service.list_active_flavors()
    return _render(
        request,
        "comercio_detail.html",
        _form_context(
            request=request,
            # The detail view contains a mutable flavor form whose POST target
            # differs from this GET route. Bind its nonce to that target so
            # native form submissions satisfy the path-bound CSRF check.
            path=f"/admin/catalog/comercios/{parsed_comercio_id}/flavor",
            extra={
                "detail": detail,
                "catalog": catalog,
                "flavor_options": flavor_options,
            },
        ),
    )


@router.post("/comercios/{comercio_id}/flavor", response_class=HTMLResponse)
def assign_flavor(
    request: Request,
    comercio_id: Annotated[str, Path()],
    payload: Annotated[FlavorAssignForm, FormParam()],
    create_service: Annotated[
        CatalogCreateService, Depends(_create_service)
    ],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "comercio_id must be a positive integer"},
            ),
            status_code=400,
        )

    try:
        _comercio, _flavor = create_service.assign_flavor(
            parsed_comercio_id, payload.flavor_comunicacion_id
        )
    except Exception as exc:  # noqa: BLE001 - panel intentionally sanitises any failure
        mapping = _map_domain_exception(exc)
        if not mapping.render_form:
            return _render(
                request,
                "not_found.html",
                _form_context(
                    request=request,
                    path=str(request.url.path),
                    extra={
                        "raw_id": str(parsed_comercio_id),
                        "resource_label": "comercio",
                    },
                ),
                status_code=mapping.status_code,
            )
        return _form_error_response(
            request=request,
            template_name="comercio_detail.html",
            status=PanelFormStatus(
                outcome="error",
                message=mapping.message,
                field_name="flavor_comunicacion_id",
                resource_id=parsed_comercio_id,
                resource_label="comercio",
            ),
            context_extra={
                "detail": service.get_commerce_detail(parsed_comercio_id),
                "catalog": service.get_commerce_catalog_navigation(
                    parsed_comercio_id
                ),
                "flavor_options": service.list_active_flavors(),
            },
            form_path=f"/admin/catalog/comercios/{parsed_comercio_id}/flavor",
            status_code=200 if mapping.render_form else mapping.status_code,
        )

    detail = service.get_commerce_detail(parsed_comercio_id)
    if detail is None:
        return _form_success_redirect(
            f"/admin/catalog/comercios/{parsed_comercio_id}"
        )

    catalog = service.get_commerce_catalog_navigation(parsed_comercio_id)
    flavor_options = service.list_active_flavors()
    is_clearing = payload.flavor_comunicacion_id is None
    if is_clearing:
        message = "Flavor limpiado. La operación no usa instrucción de LLM."
    else:
        message = "Flavor actualizado."
    return _render(
        request,
        "comercio_detail.html",
        _form_context(
            request=request,
            path=f"/admin/catalog/comercios/{parsed_comercio_id}/flavor",
            extra={
                "detail": detail,
                "catalog": catalog,
                "flavor_options": flavor_options,
                "status": PanelFormStatus(
                    outcome="success",
                    message=message,
                    resource_id=parsed_comercio_id,
                    resource_label="comercio",
                ),
            },
        ),
    )


@router.get(
    "/comercios/{comercio_id}/categorias/nueva",
    response_class=HTMLResponse,
)
def new_categoria_form(
    request: Request,
    comercio_id: Annotated[str, Path()],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "comercio_id must be a positive integer"},
            ),
            status_code=400,
        )

    detail = service.get_commerce_detail(parsed_comercio_id)
    if detail is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": comercio_id,
                    "resource_label": "comercio",
                },
            ),
            status_code=404,
        )

    return _render(
        request,
        "categoria_form.html",
        _form_context(
            request=request,
            path=str(request.url.path),
            extra={
                "detail": detail,
                "form_values": {"descripcion": "", "activo": True, "orden": 0},
                "form_error": None,
            },
        ),
    )


@router.post(
    "/comercios/{comercio_id}/categorias/nueva",
    response_class=HTMLResponse,
)
def create_categoria(
    request: Request,
    comercio_id: Annotated[str, Path()],
    create_service: Annotated[
        CatalogCreateService, Depends(_create_service)
    ],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
    descripcion: Annotated[str, Form()] = "",
    activo: Annotated[str | None, Form()] = None,
    orden: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "comercio_id must be a positive integer"},
            ),
            status_code=400,
        )

    detail = service.get_commerce_detail(parsed_comercio_id)
    if detail is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": comercio_id,
                    "resource_label": "comercio",
                },
            ),
            status_code=404,
        )

    try:
        coerced_activo = _coerce_optional_bool(activo)
        coerced_orden = _coerce_optional_int(orden)
    except ValueError as exc:
        return _re_render_categoria_form(
            request=request,
            comercio_id=parsed_comercio_id,
            service=service,
            form_values={
                "descripcion": descripcion,
                "activo": activo,
                "orden": orden,
            },
            error_message=str(exc),
        )

    try:
        row = create_service.create_categoria_producto(
            parsed_comercio_id,
            descripcion,
            coerced_activo,
            coerced_orden,
        )
    except Exception as exc:  # noqa: BLE001 - panel intentionally sanitises any failure
        mapping = _map_domain_exception(exc)
        if mapping is None:
            return _re_render_categoria_form(
                request=request,
                comercio_id=parsed_comercio_id,
                service=service,
                form_values={
                    "descripcion": descripcion,
                    "activo": activo,
                    "orden": orden,
                },
                error_message="La operación no pudo completarse. Revisá los valores e intentá nuevamente.",
            )
        return _re_render_categoria_form(
            request=request,
            comercio_id=parsed_comercio_id,
            service=service,
            form_values={
                "descripcion": descripcion,
                "activo": activo,
                "orden": orden,
            },
            error_message=mapping.message,
        )

    return _form_success_redirect(
        f"/admin/catalog/comercios/{parsed_comercio_id}?created=categoria#{row.id}"
    )


def _re_render_categoria_form(
    *,
    request: Request,
    comercio_id: int,
    service: AdministrativeCatalogPanelViewService,
    form_values: dict[str, Any],
    error_message: str,
) -> Response:
    detail = service.get_commerce_detail(comercio_id)
    if detail is None:
        return _form_success_redirect(
            f"/admin/catalog/comercios/{comercio_id}"
        )
    return _render(
        request,
        "categoria_form.html",
        _form_context(
            request=request,
            path=f"/admin/catalog/comercios/{comercio_id}/categorias/nueva",
            extra={
                "detail": detail,
                "form_values": {
                    "descripcion": form_values.get("descripcion") or "",
                    "activo": form_values.get("activo"),
                    "orden": form_values.get("orden"),
                },
                "form_error": CatalogFormError(
                    message=error_message,
                    field_name="descripcion",
                ),
            },
        ),
    )


@router.get(
    "/comercios/{comercio_id}/categorias/{categoria_id}/productos/nuevo",
    response_class=HTMLResponse,
)
def new_producto_form(
    request: Request,
    comercio_id: Annotated[str, Path()],
    categoria_id: Annotated[str, Path()],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
        parsed_categoria_id = parse_positive_int(
            categoria_id, field_name="categoria_id"
        )
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "ids must be positive integers"},
            ),
            status_code=400,
        )

    detail = service.get_commerce_detail(parsed_comercio_id)
    if detail is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": comercio_id,
                    "resource_label": "comercio",
                },
            ),
            status_code=404,
        )
    categoria = service.get_categoria_detail(
        parsed_categoria_id, expected_comercio_id=parsed_comercio_id
    )
    if categoria is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": categoria_id,
                    "resource_label": "categoría",
                },
            ),
            status_code=404,
        )

    return _render(
        request,
        "producto_form.html",
        _form_context(
            request=request,
            path=str(request.url.path),
            extra={
                "detail": detail,
                "categoria": categoria,
                "form_values": {
                    "nombre": "",
                    "descripcion": "",
                    "activo": True,
                    "disponible": True,
                    "orden": 0,
                },
                "form_error": None,
            },
        ),
    )


@router.post(
    "/comercios/{comercio_id}/categorias/{categoria_id}/productos/nuevo",
    response_class=HTMLResponse,
)
def create_producto(
    request: Request,
    comercio_id: Annotated[str, Path()],
    categoria_id: Annotated[str, Path()],
    create_service: Annotated[
        CatalogCreateService, Depends(_create_service)
    ],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
    nombre: Annotated[str, Form()] = "",
    descripcion: Annotated[str | None, Form()] = None,
    activo: Annotated[str | None, Form()] = None,
    disponible: Annotated[str | None, Form()] = None,
    orden: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
        parsed_categoria_id = parse_positive_int(
            categoria_id, field_name="categoria_id"
        )
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "ids must be positive integers"},
            ),
            status_code=400,
        )

    detail = service.get_commerce_detail(parsed_comercio_id)
    if detail is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": comercio_id,
                    "resource_label": "comercio",
                },
            ),
            status_code=404,
        )

    categoria = service.get_categoria_detail(
        parsed_categoria_id, expected_comercio_id=parsed_comercio_id
    )
    if categoria is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": categoria_id,
                    "resource_label": "categoría",
                },
            ),
            status_code=404,
        )

    try:
        coerced_activo = _coerce_optional_bool(activo)
        coerced_disponible = _coerce_optional_bool(disponible)
        coerced_orden = _coerce_optional_int(orden)
    except ValueError as exc:
        return _re_render_producto_form(
            request=request,
            comercio_id=parsed_comercio_id,
            categoria_id=parsed_categoria_id,
            service=service,
            form_values={
                "nombre": nombre,
                "descripcion": descripcion,
                "activo": activo,
                "disponible": disponible,
                "orden": orden,
            },
            error_message=str(exc),
        )

    cleaned_descripcion = (
        descripcion.strip() if isinstance(descripcion, str) else None
    )
    if cleaned_descripcion == "":
        cleaned_descripcion = None

    try:
        row = create_service.create_producto(
            parsed_categoria_id,
            nombre,
            cleaned_descripcion,
            coerced_activo,
            coerced_disponible,
            coerced_orden,
        )
    except Exception as exc:  # noqa: BLE001 - panel intentionally sanitises any failure
        mapping = _map_domain_exception(exc)
        return _re_render_producto_form(
            request=request,
            comercio_id=parsed_comercio_id,
            categoria_id=parsed_categoria_id,
            service=service,
            form_values={
                "nombre": nombre,
                "descripcion": descripcion,
                "activo": activo,
                "disponible": disponible,
                "orden": orden,
            },
            error_message=mapping.message,
        )

    return _form_success_redirect(
        f"/admin/catalog/comercios/{parsed_comercio_id}?created=producto#{row.id}"
    )


def _re_render_producto_form(
    *,
    request: Request,
    comercio_id: int,
    categoria_id: int,
    service: AdministrativeCatalogPanelViewService,
    form_values: dict[str, Any],
    error_message: str,
) -> Response:
    detail = service.get_commerce_detail(comercio_id)
    categoria = service.get_categoria_detail(
        categoria_id, expected_comercio_id=comercio_id
    )
    if detail is None or categoria is None:
        return _form_success_redirect(
            f"/admin/catalog/comercios/{comercio_id}"
        )
    return _render(
        request,
        "producto_form.html",
        _form_context(
            request=request,
            path=f"/admin/catalog/comercios/{comercio_id}/categorias/{categoria_id}/productos/nuevo",
            extra={
                "detail": detail,
                "categoria": categoria,
                "form_values": {
                    "nombre": form_values.get("nombre") or "",
                    "descripcion": form_values.get("descripcion") or "",
                    "activo": form_values.get("activo"),
                    "disponible": form_values.get("disponible"),
                    "orden": form_values.get("orden"),
                },
                "form_error": CatalogFormError(
                    message=error_message,
                    field_name="nombre",
                ),
            },
        ),
    )


@router.get(
    "/comercios/{comercio_id}/presentaciones/nueva",
    response_class=HTMLResponse,
)
def new_presentacion_form(
    request: Request,
    comercio_id: Annotated[str, Path()],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "comercio_id must be a positive integer"},
            ),
            status_code=400,
        )

    detail = service.get_commerce_detail(parsed_comercio_id)
    if detail is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": comercio_id,
                    "resource_label": "comercio",
                },
            ),
            status_code=404,
        )

    return _render(
        request,
        "presentacion_form.html",
        _form_context(
            request=request,
            path=str(request.url.path),
            extra={
                "detail": detail,
                "form_values": {"codigo": "", "descripcion": "", "activo": True, "orden": 0},
                "form_error": None,
            },
        ),
    )


@router.post(
    "/comercios/{comercio_id}/presentaciones/nueva",
    response_class=HTMLResponse,
)
def create_presentacion(
    request: Request,
    comercio_id: Annotated[str, Path()],
    create_service: Annotated[
        CatalogCreateService, Depends(_create_service)
    ],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
    codigo: Annotated[str, Form()] = "",
    descripcion: Annotated[str, Form()] = "",
    activo: Annotated[str | None, Form()] = None,
    orden: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "comercio_id must be a positive integer"},
            ),
            status_code=400,
        )

    detail = service.get_commerce_detail(parsed_comercio_id)
    if detail is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": comercio_id,
                    "resource_label": "comercio",
                },
            ),
            status_code=404,
        )

    try:
        coerced_activo = _coerce_optional_bool(activo)
        coerced_orden = _coerce_optional_int(orden)
    except ValueError as exc:
        return _re_render_presentacion_form(
            request=request,
            comercio_id=parsed_comercio_id,
            service=service,
            form_values={
                "codigo": codigo,
                "descripcion": descripcion,
                "activo": activo,
                "orden": orden,
            },
            error_message=str(exc),
        )

    try:
        row = create_service.create_presentacion(
            parsed_comercio_id,
            codigo,
            descripcion,
            coerced_activo,
            coerced_orden,
        )
    except Exception as exc:  # noqa: BLE001 - panel intentionally sanitises any failure
        mapping = _map_domain_exception(exc)
        return _re_render_presentacion_form(
            request=request,
            comercio_id=parsed_comercio_id,
            service=service,
            form_values={
                "codigo": codigo,
                "descripcion": descripcion,
                "activo": activo,
                "orden": orden,
            },
            error_message=mapping.message,
        )

    return _form_success_redirect(
        f"/admin/catalog/comercios/{parsed_comercio_id}?created=presentacion#{row.id}"
    )


def _re_render_presentacion_form(
    *,
    request: Request,
    comercio_id: int,
    service: AdministrativeCatalogPanelViewService,
    form_values: dict[str, Any],
    error_message: str,
) -> Response:
    detail = service.get_commerce_detail(comercio_id)
    if detail is None:
        return _form_success_redirect(
            f"/admin/catalog/comercios/{comercio_id}"
        )
    return _render(
        request,
        "presentacion_form.html",
        _form_context(
            request=request,
            path=f"/admin/catalog/comercios/{comercio_id}/presentaciones/nueva",
            extra={
                "detail": detail,
                "form_values": {
                    "codigo": form_values.get("codigo") or "",
                    "descripcion": form_values.get("descripcion") or "",
                    "activo": form_values.get("activo"),
                    "orden": form_values.get("orden"),
                },
                "form_error": CatalogFormError(
                    message=error_message,
                    field_name="descripcion",
                ),
            },
        ),
    )


@router.get(
    "/comercios/{comercio_id}/productos/{producto_id}/presentaciones/{presentacion_id}/precio/nuevo",
    response_class=HTMLResponse,
)
def new_precio_form(
    request: Request,
    comercio_id: Annotated[str, Path()],
    producto_id: Annotated[str, Path()],
    presentacion_id: Annotated[str, Path()],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
        parsed_producto_id = parse_positive_int(
            producto_id, field_name="producto_id"
        )
        parsed_presentacion_id = parse_positive_int(
            presentacion_id, field_name="presentacion_id"
        )
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "ids must be positive integers"},
            ),
            status_code=400,
        )

    detail = service.get_commerce_detail(parsed_comercio_id)
    if detail is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={
                    "raw_id": comercio_id,
                    "resource_label": "comercio",
                },
            ),
            status_code=404,
        )

    stmt_url = (
        f"/admin/catalog/comercios/{parsed_comercio_id}"
        f"/productos/{parsed_producto_id}"
        f"/presentaciones/{parsed_presentacion_id}/precio/nuevo"
    )

    pp_id = _compute_pp_id(
        service=service,
        comercio_id=parsed_comercio_id,
        producto_id=parsed_producto_id,
        presentacion_id=parsed_presentacion_id,
    )
    if pp_id is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=stmt_url,
                extra={
                    "raw_id": f"{producto_id}/{presentacion_id}",
                    "resource_label": "producto-presentación",
                },
            ),
            status_code=404,
        )

    association = service.find_producto_presentacion(
        pp_id,
        expected_comercio_id=parsed_comercio_id,
    )
    if association is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=stmt_url,
                extra={
                    "raw_id": f"{producto_id}/{presentacion_id}",
                    "resource_label": "producto-presentación",
                },
            ),
            status_code=404,
        )

    return _render(
        request,
        "precio_form.html",
        _form_context(
            request=request,
            path=stmt_url,
            extra={
                "detail": detail,
                "association": association,
                "form_values": {"precio": ""},
                "form_error": None,
            },
        ),
    )


@router.post(
    "/comercios/{comercio_id}/productos/{producto_id}/presentaciones/{presentacion_id}/precio/nuevo",
    response_class=HTMLResponse,
)
def create_precio(
    request: Request,
    comercio_id: Annotated[str, Path()],
    producto_id: Annotated[str, Path()],
    presentacion_id: Annotated[str, Path()],
    create_service: Annotated[
        CatalogCreateService, Depends(_create_service)
    ],
    service: Annotated[
        AdministrativeCatalogPanelViewService, Depends(_view_service)
    ],
    precio: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        parsed_comercio_id = parse_positive_int(comercio_id, field_name="comercio_id")
        parsed_producto_id = parse_positive_int(
            producto_id, field_name="producto_id"
        )
        parsed_presentacion_id = parse_positive_int(
            presentacion_id, field_name="presentacion_id"
        )
    except ValueError:
        return _render(
            request,
            "bad_request.html",
            _form_context(
                request=request,
                path=str(request.url.path),
                extra={"message": "ids must be positive integers"},
            ),
            status_code=400,
        )

    pp_id = _compute_pp_id(
        service=service,
        comercio_id=parsed_comercio_id,
        producto_id=parsed_producto_id,
        presentacion_id=parsed_presentacion_id,
    )

    stmt_url = (
        f"/admin/catalog/comercios/{parsed_comercio_id}"
        f"/productos/{parsed_producto_id}"
        f"/presentaciones/{parsed_presentacion_id}/precio/nuevo"
    )

    if pp_id is None:
        return _render(
            request,
            "not_found.html",
            _form_context(
                request=request,
                path=stmt_url,
                extra={
                    "raw_id": f"{producto_id}/{presentacion_id}",
                    "resource_label": "producto-presentación",
                },
            ),
            status_code=404,
        )

    try:
        coerced_precio = _parse_decimal(precio)
    except ValueError as exc:
        return _re_render_precio_form(
            request=request,
            comercio_id=parsed_comercio_id,
            pp_id=pp_id,
            service=service,
            precio_value=precio or "",
            error_message=str(exc),
            stmt_url=stmt_url,
        )

    try:
        row = create_service.create_precio(pp_id, coerced_precio)
    except Exception as exc:  # noqa: BLE001 - panel intentionally sanitises any failure
        mapping = _map_domain_exception(exc)
        return _re_render_precio_form(
            request=request,
            comercio_id=parsed_comercio_id,
            pp_id=pp_id,
            service=service,
            precio_value=precio or "",
            error_message=mapping.message,
            stmt_url=stmt_url,
        )

    return _form_success_redirect(
        f"/admin/catalog/comercios/{parsed_comercio_id}?created=precio#{row.id}"
    )


def _compute_pp_id(
    *,
    service: AdministrativeCatalogPanelViewService,
    comercio_id: int,
    producto_id: int,
    presentacion_id: int,
) -> int | None:
    """Resolve the ``ProductoPresentacion.id`` for the price form.

    The helper enforces commerce isolation: a ``Producto`` /
    ``Presentacion`` pair from a foreign comercio never returns a
    valid id, so the panel cannot post a price for a foreign
    scope. The lookup mirrors :meth:`AdministrativeCatalogPanelViewService.find_producto_presentacion_for_pp`
    so both the GET and POST paths use the same gate.
    """
    association = service.find_producto_presentacion_for_pp(
        producto_id=producto_id,
        presentacion_id=presentacion_id,
        expected_comercio_id=comercio_id,
    )
    if association is None:
        return None
    return association.id


def _re_render_precio_form(
    *,
    request: Request,
    comercio_id: int,
    pp_id: int | None,
    service: AdministrativeCatalogPanelViewService,
    precio_value: str,
    error_message: str,
    stmt_url: str,
) -> Response:
    detail = service.get_commerce_detail(comercio_id)
    if detail is None or pp_id is None:
        return _form_success_redirect(
            f"/admin/catalog/comercios/{comercio_id}"
        )
    association = service.find_producto_presentacion(
        pp_id, expected_comercio_id=comercio_id
    )
    if association is None:
        return _form_success_redirect(
            f"/admin/catalog/comercios/{comercio_id}"
        )
    return _render(
        request,
        "precio_form.html",
        _form_context(
            request=request,
            path=stmt_url,
            extra={
                "detail": detail,
                "association": association,
                "form_values": {"precio": precio_value},
                "form_error": CatalogFormError(
                    message=error_message,
                    field_name="precio",
                ),
            },
        ),
    )


def _build_paginator_url(
    *,
    base: str,
    params: dict[str, Any],
) -> str:
    """Build a URL keeping only the non-empty parameters."""
    cleaned = {key: value for key, value in params.items() if value not in (None, "")}
    if not cleaned:
        return base
    return f"{base}?{urlencode(cleaned)}"


__all__ = ["router"]
