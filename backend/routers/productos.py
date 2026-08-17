from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.dependencies import get_session, require_admin_token
from backend.schemas.producto import ProductoCreate, ProductoResponse
from backend.services.catalog_create_service import CatalogCreateService
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    DuplicateProductoNombre,
    InvalidProducto,
    ProductoNotFound,
)

router = APIRouter(
    tags=["productos"],
    dependencies=[Depends(require_admin_token)],
)


def _create_service(
    session: Annotated[Session, Depends(get_session)],
) -> CatalogCreateService:
    settings = load_settings()
    return CatalogCreateService(session=session, settings=settings)


@router.get(
    "/categorias-productos/{categoria_producto_id}/productos",
    response_model=list[ProductoResponse],
)
def list_productos_by_categoria(
    categoria_producto_id: int,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> list[ProductoResponse]:
    try:
        rows = service._producto_service.list_by_categoria(categoria_producto_id)
    except CategoriaProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [ProductoResponse.model_validate(row) for row in rows]


@router.get(
    "/comercios/{comercio_id}/productos",
    response_model=list[ProductoResponse],
)
def list_productos_by_comercio(
    comercio_id: int,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> list[ProductoResponse]:
    try:
        rows = service._producto_service.list_by_comercio(comercio_id)
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [ProductoResponse.model_validate(row) for row in rows]


@router.get("/productos/{producto_id}", response_model=ProductoResponse)
def get_producto(
    producto_id: int,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> ProductoResponse:
    try:
        row = service._producto_service.get_by_id(producto_id)
    except ProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ProductoResponse.model_validate(row)


@router.post(
    "/categorias-productos/{categoria_producto_id}/productos",
    response_model=ProductoResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_producto(
    categoria_producto_id: int,
    payload: ProductoCreate,
    service: Annotated[CatalogCreateService, Depends(_create_service)],
) -> ProductoResponse:
    try:
        row = service.create_producto(
            categoria_producto_id,
            payload.nombre,
            payload.descripcion,
            payload.activo,
            payload.disponible,
            payload.orden,
        )
    except CategoriaProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidProducto as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DuplicateProductoNombre as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return ProductoResponse.model_validate(row)


__all__ = ["router"]