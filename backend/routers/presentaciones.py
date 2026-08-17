from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.dependencies import get_session, require_admin_token
from backend.schemas.presentacion import PresentacionCreate, PresentacionResponse
from backend.services.catalog_create_service import CatalogCreateService
from backend.services.exceptions import (
    ComercioNotFound,
    DuplicatePresentacionCodigo,
    DuplicatePresentacionDescripcion,
    InvalidPresentacion,
    PresentacionNotFound,
)

router = APIRouter(
    tags=["presentaciones"],
    dependencies=[Depends(require_admin_token)],
)


def _create_service(
    session: Annotated[Session, Depends(get_session)],
) -> CatalogCreateService:
    settings = load_settings()
    return CatalogCreateService(session=session, settings=settings)


@router.get(
    "/comercios/{comercio_id}/presentaciones",
    response_model=list[PresentacionResponse],
)
def list_presentaciones(
    comercio_id: int,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> list[PresentacionResponse]:
    try:
        rows = service._presentacion_service.list_by_comercio(comercio_id)
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [PresentacionResponse.model_validate(row) for row in rows]


@router.get(
    "/presentaciones/{presentacion_id}",
    response_model=PresentacionResponse,
)
def get_presentacion(
    presentacion_id: int,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> PresentacionResponse:
    try:
        row = service._presentacion_service.get_by_id(presentacion_id)
    except PresentacionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return PresentacionResponse.model_validate(row)


@router.post(
    "/comercios/{comercio_id}/presentaciones",
    response_model=PresentacionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_presentacion(
    comercio_id: int,
    payload: PresentacionCreate,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> PresentacionResponse:
    try:
        row = service.create_presentacion(
            comercio_id,
            payload.codigo,
            payload.descripcion,
            payload.activo,
            payload.orden,
        )
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidPresentacion as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (DuplicatePresentacionCodigo, DuplicatePresentacionDescripcion) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return PresentacionResponse.model_validate(row)


__all__ = ["router"]