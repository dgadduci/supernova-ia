"""Server-rendered pilot order operations panel.

This router exposes the human-readable inspection surface for the
pilot operator under ``/admin/pilot/orders``. It is strictly
read-only and does not mutate any Pedido, Session, Cliente, provider
receipt or outbound row. It does not commit, rollback, flush, refresh,
begin or close the database session; the request-level dependency
remains the transaction owner.

The panel uses an HTTP Basic challenge whose password validates
against the existing configured administrative token with a
constant-time comparison. The username is ignored. The existing
``X-Admin-Token`` contract for the JSON API is unchanged.
"""
from __future__ import annotations

from pathlib import Path as PathLib
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.dependencies import get_session, require_admin_pilot_basic
from backend.models import EstadoPedido
from backend.services.pilot_order_operations_view_service import (
    ALLOWED_PAGE_SIZES,
    InvalidComercioId,
    InvalidListFilter,
    InvalidPedidoId,
    ListFilters,
    PilotOrderOperationsViewService,
    parse_comercio_id,
    parse_list_filters,
    parse_pedido_id,
)

_TEMPLATE_DIR = (
    PathLib(__file__).resolve().parents[1] / "templates" / "admin_pilot_orders"
)

_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
_templates.env.autoescape = True

_ESTADO_VALUES: tuple[str, ...] = tuple(member.value for member in EstadoPedido)


def _service(
    session: Annotated[Session, Depends(get_session)],
) -> PilotOrderOperationsViewService:
    return PilotOrderOperationsViewService(session)


router = APIRouter(
    prefix="/admin/pilot/orders",
    tags=["admin-pilot-orders"],
    dependencies=[Depends(require_admin_pilot_basic)],
)


def _render(
    request: Request,
    template_name: str,
    context: dict[str, object],
) -> HTMLResponse:
    return _templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
        status_code=200,
    )


def _build_list_url(
    *,
    base: str,
    params: dict[str, object],
) -> str:
    encoded = urlencode(
        [(key, value) for key, value in params.items() if value not in (None, "")],
        doseq=False,
    )
    if not encoded:
        return base
    return f"{base}?{encoded}"


@router.get("", response_class=HTMLResponse)
def list_orders(
    request: Request,
    service: Annotated[PilotOrderOperationsViewService, Depends(_service)],
    raw_from: Annotated[str | None, Query(alias="from")] = None,
    raw_to: Annotated[str | None, Query(alias="to")] = None,
    raw_comercio_id: Annotated[str | None, Query(alias="comercio_id")] = None,
    raw_estado: Annotated[str | None, Query(alias="estado")] = None,
    raw_page: Annotated[str | None, Query(alias="page")] = None,
    raw_page_size: Annotated[str | None, Query(alias="page_size")] = None,
) -> Response:
    try:
        filters: ListFilters = parse_list_filters(
            raw_from=raw_from,
            raw_to=raw_to,
            raw_comercio_id=raw_comercio_id,
            raw_estado=raw_estado,
            raw_page=raw_page,
            raw_page_size=raw_page_size,
        )
    except InvalidListFilter as exc:
        return _templates.TemplateResponse(
            request=request,
            name="bad_request.html",
            context={"message": str(exc)},
            status_code=400,
        )

    list_view = service.list_orders(filters)
    total_pages = (
        (list_view.total + list_view.page_size - 1) // list_view.page_size
        if list_view.total > 0
        else 0
    )

    def paginator_url(page: int) -> str:
        params = {
            "from": filters.from_date.isoformat(),
            "to": filters.to_date.isoformat(),
            "comercio_id": filters.comercio_id,
            "estado": filters.estado.value if filters.estado else None,
            "page_size": filters.page_size,
            "page": page,
        }
        return _build_list_url(
            base="/admin/pilot/orders",
            params=params,
        )

    return _render(
        request,
        "list.html",
        {
            "filters": filters,
            "list_view": list_view,
            "total_pages": total_pages,
            "estado_choices": _ESTADO_VALUES,
            "page_size_choices": ALLOWED_PAGE_SIZES,
            "paginator_url": paginator_url,
        },
    )


@router.get("/{pedido_id}", response_class=HTMLResponse)
def detail_order(
    request: Request,
    pedido_id: Annotated[str, Path()],
    service: Annotated[PilotOrderOperationsViewService, Depends(_service)],
) -> Response:
    try:
        parsed_id = parse_pedido_id(pedido_id)
    except InvalidPedidoId:
        return _templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"raw_id": pedido_id},
            status_code=404,
        )

    detail = service.get_detail(parsed_id)
    if detail is None:
        return _templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"raw_id": pedido_id},
            status_code=404,
        )

    history = service.get_provider_history(
        cliente_id=detail.client.id,
        comercio_id=detail.commerce.id,
        zona_horaria=detail.commerce.zona_horaria,
    )

    return _render(
        request,
        "detail.html",
        {
            "detail": detail,
            "history": history,
        },
    )


@router.get("/commerce/{comercio_id}/catalog", response_class=HTMLResponse)
def commerce_catalog(
    request: Request,
    comercio_id: Annotated[str, Path()],
    service: Annotated[PilotOrderOperationsViewService, Depends(_service)],
) -> Response:
    try:
        parsed_comercio_id = parse_comercio_id(comercio_id)
    except InvalidComercioId:
        return _templates.TemplateResponse(
            request=request,
            name="bad_request.html",
            context={"message": "comercio_id must be a positive integer"},
            status_code=400,
        )

    catalog_view = service.get_commerce_catalog_price_availability(
        parsed_comercio_id
    )
    if catalog_view is None:
        return _templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"raw_id": comercio_id},
            status_code=404,
        )

    return _render(
        request,
        "catalog.html",
        {"catalog_view": catalog_view},
    )


__all__ = ["_ESTADO_VALUES", "_build_list_url", "router"]
