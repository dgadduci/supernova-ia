from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.dependencies import get_session, require_admin_token
from backend.llm.embedding_client import OllamaEmbeddingClient
from backend.schemas.categoria_producto import (
    CategoriaProductoCreate,
    CategoriaProductoResponse,
)
from backend.services.categoria_producto_service import CategoriaProductoService
from backend.services.catalog_embedding_synchronization_service import (
    CatalogEmbeddingSynchronizationService,
)
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    InvalidCategoriaProducto,
)

router = APIRouter(
    tags=["categorias-productos"],
    dependencies=[Depends(require_admin_token)],
)


def _service(
    session: Annotated[Session, Depends(get_session)],
) -> CategoriaProductoService:
    return CategoriaProductoService(session)


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
    session: Annotated[Any, Depends(get_session)],
    service: CategoriaProductoService = Depends(_service),
    sync_service: CatalogEmbeddingSynchronizationService = Depends(_sync_service),
) -> CategoriaProductoResponse:
    try:
        row = service.create(
            comercio_id,
            payload.descripcion,
            payload.activo,
            payload.orden,
        )
        session.commit()
    except ComercioNotFound as e:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidCategoriaProducto as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        session.rollback()
        raise
    try:
        sync_service.synchronize_categoria(int(row.id))
        session.commit()
    except Exception:
        session.rollback()
    return CategoriaProductoResponse.model_validate(row)
