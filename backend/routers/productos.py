from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.dependencies import get_session, require_admin_token
from backend.llm.embedding_client import OllamaEmbeddingClient
from backend.schemas.producto import ProductoCreate, ProductoResponse
from backend.services.catalog_embedding_synchronization_service import (
    CatalogEmbeddingSynchronizationService,
)
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    DuplicateProductoNombre,
    InvalidProducto,
    ProductoNotFound,
)
from backend.services.producto_service import ProductoService

router = APIRouter(
    tags=["productos"],
    dependencies=[Depends(require_admin_token)],
)


def _service(session: Annotated[Session, Depends(get_session)]) -> ProductoService:
    return ProductoService(session)


def _sync_service(
    session: Annotated[Session, Depends(get_session)],
) -> CatalogEmbeddingSynchronizationService:
    settings = load_settings()
    embedding_client = OllamaEmbeddingClient(settings)
    return CatalogEmbeddingSynchronizationService(
        session=session,
        embedding_client=embedding_client,
        settings=settings,
    )


@router.get(
    "/categorias-productos/{categoria_producto_id}/productos",
    response_model=list[ProductoResponse],
)
def list_productos_by_categoria(
    categoria_producto_id: int,
    service: ProductoService = Depends(_service),
) -> list[ProductoResponse]:
    try:
        return [
            ProductoResponse.model_validate(product)
            for product in service.list_by_categoria(categoria_producto_id)
        ]
    except CategoriaProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/comercios/{comercio_id}/productos",
    response_model=list[ProductoResponse],
)
def list_productos_by_comercio(
    comercio_id: int,
    service: ProductoService = Depends(_service),
) -> list[ProductoResponse]:
    try:
        return [
            ProductoResponse.model_validate(product)
            for product in service.list_by_comercio(comercio_id)
        ]
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/productos/{producto_id}", response_model=ProductoResponse)
def get_producto(
    producto_id: int,
    service: ProductoService = Depends(_service),
) -> ProductoResponse:
    try:
        return ProductoResponse.model_validate(service.get_by_id(producto_id))
    except ProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post(
    "/categorias-productos/{categoria_producto_id}/productos",
    response_model=ProductoResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_producto(
    categoria_producto_id: int,
    payload: ProductoCreate,
    session: Annotated[Any, Depends(get_session)],
    service: ProductoService = Depends(_service),
    sync_service: CatalogEmbeddingSynchronizationService = Depends(_sync_service),
) -> ProductoResponse:
    try:
        row = service.create(
            categoria_producto_id,
            payload.nombre,
            payload.descripcion,
            payload.activo,
            payload.disponible,
            payload.orden,
        )
        session.commit()
    except CategoriaProductoNotFound as e:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidProducto as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DuplicateProductoNombre as e:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception:
        session.rollback()
        raise
    try:
        sync_service.synchronize_producto(int(row.id))
        session.commit()
    except Exception:
        session.rollback()
    return ProductoResponse.model_validate(row)
