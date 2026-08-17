from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.dependencies import get_session, require_admin_token
from backend.schemas.precio import PrecioCreate, PrecioResponse
from backend.services.catalog_create_service import CatalogCreateService
from backend.services.exceptions import (
    DuplicatePrecio,
    InvalidPrecio,
    PrecioNotFound,
    ProductoPresentacionNotFound,
)

router = APIRouter(
    tags=["precios"],
    dependencies=[Depends(require_admin_token)],
)


def _create_service(
    session: Annotated[Session, Depends(get_session)],
) -> CatalogCreateService:
    settings = load_settings()
    return CatalogCreateService(session=session, settings=settings)


@router.get(
    "/producto-presentaciones/{producto_presentacion_id}/precio",
    response_model=PrecioResponse,
)
def get_precio_by_producto_presentacion(
    producto_presentacion_id: int,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> PrecioResponse:
    try:
        return PrecioResponse.model_validate(
            service._precio_service.get_by_producto_presentacion(
                producto_presentacion_id
            )
        )
    except (ProductoPresentacionNotFound, PrecioNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/precios/{precio_id}", response_model=PrecioResponse)
def get_precio(
    precio_id: int,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> PrecioResponse:
    try:
        return PrecioResponse.model_validate(
            service._precio_service.get_by_id(precio_id)
        )
    except PrecioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post(
    "/producto-presentaciones/{producto_presentacion_id}/precio",
    response_model=PrecioResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_precio(
    producto_presentacion_id: int,
    payload: PrecioCreate,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> PrecioResponse:
    try:
        return PrecioResponse.model_validate(
            service.create_precio(producto_presentacion_id, payload.precio)
        )
    except ProductoPresentacionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidPrecio as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DuplicatePrecio as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


__all__ = ["router"]