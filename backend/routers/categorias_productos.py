from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.dependencies import get_session, require_admin_token
from backend.schemas.categoria_producto import (
    CategoriaProductoCreate,
    CategoriaProductoResponse,
)
from backend.services.catalog_create_service import CatalogCreateService
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    InvalidCategoriaProducto,
)

router = APIRouter(
    tags=["categorias-productos"],
    dependencies=[Depends(require_admin_token)],
)


def _create_service(
    session: Annotated[Session, Depends(get_session)],
) -> CatalogCreateService:
    settings = load_settings()
    return CatalogCreateService(session=session, settings=settings)


@router.get(
    "/comercios/{comercio_id}/categorias-productos",
    response_model=list[CategoriaProductoResponse],
)
def list_categorias_productos(
    comercio_id: int,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> list[CategoriaProductoResponse]:
    try:
        categorias = service._categoria_service.list_by_comercio(comercio_id)
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [CategoriaProductoResponse.model_validate(row) for row in categorias]


@router.get(
    "/categorias-productos/{categoria_producto_id}",
    response_model=CategoriaProductoResponse,
)
def get_categoria_producto(
    categoria_producto_id: int,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> CategoriaProductoResponse:
    try:
        row = service._categoria_service.get_by_id(categoria_producto_id)
    except CategoriaProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return CategoriaProductoResponse.model_validate(row)


@router.post(
    "/comercios/{comercio_id}/categorias-productos",
    response_model=CategoriaProductoResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_categoria_producto(
    comercio_id: int,
    payload: CategoriaProductoCreate,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> CategoriaProductoResponse:
    try:
        row = service.create_categoria_producto(
            comercio_id,
            payload.descripcion,
            payload.activo,
            payload.orden,
        )
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidCategoriaProducto as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return CategoriaProductoResponse.model_validate(row)


__all__ = ["router"]