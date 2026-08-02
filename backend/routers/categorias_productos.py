from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dependencies import get_session
from backend.schemas.categoria_producto import (
    CategoriaProductoCreate,
    CategoriaProductoResponse,
)
from backend.services.categoria_producto_service import CategoriaProductoService
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    InvalidCategoriaProducto,
)

router = APIRouter(tags=["categorias-productos"])


def _service(session: Session = Depends(get_session)) -> CategoriaProductoService:
    return CategoriaProductoService(session)


@router.get(
    "/comercios/{comercio_id}/categorias-productos",
    response_model=list[CategoriaProductoResponse],
)
def list_categorias_productos(
    comercio_id: int,
    service: CategoriaProductoService = Depends(_service),
) -> list[CategoriaProductoResponse]:
    try:
        return [
            CategoriaProductoResponse.model_validate(category)
            for category in service.list_by_comercio(comercio_id)
        ]
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/categorias-productos/{categoria_producto_id}",
    response_model=CategoriaProductoResponse,
)
def get_categoria_producto(
    categoria_producto_id: int,
    service: CategoriaProductoService = Depends(_service),
) -> CategoriaProductoResponse:
    try:
        return CategoriaProductoResponse.model_validate(
            service.get_by_id(categoria_producto_id)
        )
    except CategoriaProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post(
    "/comercios/{comercio_id}/categorias-productos",
    response_model=CategoriaProductoResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_categoria_producto(
    comercio_id: int,
    payload: CategoriaProductoCreate,
    service: CategoriaProductoService = Depends(_service),
) -> CategoriaProductoResponse:
    try:
        return CategoriaProductoResponse.model_validate(
            service.create(
                comercio_id,
                payload.descripcion,
                payload.activo,
                payload.orden,
            )
        )
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidCategoriaProducto as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
