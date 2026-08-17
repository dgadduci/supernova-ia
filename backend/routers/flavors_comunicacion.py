"""Administrative surface for the global communication flavor catalog.

The router exposes the two endpoints authorised by the OpenSpec
proposal:

* ``GET /flavors-comunicacion`` — read-only listing of active
  flavors. The administrative response includes each persisted
  ``instruccion_llm`` so an authenticated administrator can inspect
  the exact directive used by the outbound LLM styler. The mapping
  is total, read-only and never mutates the catalog.
* ``PUT /comercios/{comercio_id}/flavor-comunicacion`` — focused
  authenticated operation that mutates only one
  ``Comercio.flavor_comunicacion_id``. The payload accepts only a
  global flavor ID. Unknown or inactive global flavor IDs are
  rejected without mutating the commerce. The response remains the
  safe ``ComercioResponse`` summary and never echoes
  ``instruccion_llm``.

Both endpoints require the existing admin header token. The router
delegates the assignment path to :class:`CatalogCreateService`,
which owns the application transaction boundary: it commits on
success and rolls back when the service raises a domain error. The
selection service only ``flush()`` es the change so the operation
can own the commit / rollback. The GET listing path does not control
the session transaction at all and must never issue commit,
rollback, flush, refresh, begin, begin_nested or close.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.dependencies import get_session, require_admin_token
from backend.schemas.comercio import ComercioResponse
from backend.schemas.comunicacion_flavor import (
    ComercioFlavorAssignRequest,
    FlavorComunicacionResponse,
)
from backend.services.catalog_create_service import CatalogCreateService
from backend.services.comunicacion_flavor_service import (
    ComunicacionFlavorService,
)
from backend.services.exceptions import (
    ComercioNotFound,
    FlavorComunicacionInactivo,
    FlavorComunicacionNotFound,
)

router = APIRouter(
    tags=["flavors-comunicacion"],
    dependencies=[Depends(require_admin_token)],
)


def _service(session: Annotated[Session, Depends(get_session)]) -> ComunicacionFlavorService:
    return ComunicacionFlavorService(session)


def _create_service(
    session: Annotated[Session, Depends(get_session)],
) -> CatalogCreateService:
    settings = load_settings()
    flavor_service = ComunicacionFlavorService(session)
    return CatalogCreateService(
        session=session,
        settings=settings,
        flavor_service=flavor_service,
    )


@router.get(
    "/flavors-comunicacion",
    response_model=list[FlavorComunicacionResponse],
)
def list_flavors_comunicacion(
    service: Annotated[ComunicacionFlavorService, Depends(_service)],
) -> list[FlavorComunicacionResponse]:
    return [
        FlavorComunicacionResponse.model_validate(flavor)
        for flavor in service.list_active_flavors()
    ]


@router.put(
    "/comercios/{comercio_id}/flavor-comunicacion",
    response_model=ComercioResponse,
)
def assign_flavor_comunicacion(
    comercio_id: int,
    payload: ComercioFlavorAssignRequest,
    create_service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> ComercioResponse:
    try:
        comercio, _flavor = create_service.assign_flavor(
            comercio_id,
            payload.flavor_comunicacion_id,
        )
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FlavorComunicacionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FlavorComunicacionInactivo as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return ComercioResponse.model_validate(comercio)


__all__ = ["router"]