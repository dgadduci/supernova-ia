from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config.settings import load_settings
from backend.dependencies import get_session, require_admin_token
from backend.llm.embedding_client import OllamaEmbeddingClient
from backend.schemas.presentacion import PresentacionCreate, PresentacionResponse
from backend.services.catalog_embedding_synchronization_service import (
    CatalogEmbeddingSynchronizationService,
)
from backend.services.exceptions import (
    ComercioNotFound,
    DuplicatePresentacionCodigo,
    DuplicatePresentacionDescripcion,
    InvalidPresentacion,
    PresentacionNotFound,
)
from backend.services.presentacion_service import PresentacionService

router = APIRouter(
    tags=["presentaciones"],
    dependencies=[Depends(require_admin_token)],
)


def _service(
    session: Annotated[Session, Depends(get_session)],
) -> PresentacionService:
    return PresentacionService(session)


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
    "/comercios/{comercio_id}/presentaciones",
    response_model=list[PresentacionResponse],
)
def list_presentaciones(
    comercio_id: int,
    service: PresentacionService = Depends(_service),
) -> list[PresentacionResponse]:
    try:
        return [
            PresentacionResponse.model_validate(presentation)
            for presentation in service.list_by_comercio(comercio_id)
        ]
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/presentaciones/{presentacion_id}",
    response_model=PresentacionResponse,
)
def get_presentacion(
    presentacion_id: int,
    service: PresentacionService = Depends(_service),
) -> PresentacionResponse:
    try:
        return PresentacionResponse.model_validate(service.get_by_id(presentacion_id))
    except PresentacionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post(
    "/comercios/{comercio_id}/presentaciones",
    response_model=PresentacionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_presentacion(
    comercio_id: int,
    payload: PresentacionCreate,
    session: Annotated[Any, Depends(get_session)],
    service: PresentacionService = Depends(_service),
    sync_service: CatalogEmbeddingSynchronizationService = Depends(_sync_service),
) -> PresentacionResponse:
    try:
        row = service.create(
            comercio_id,
            payload.codigo,
            payload.descripcion,
            payload.activo,
            payload.orden,
        )
        session.commit()
    except ComercioNotFound as e:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidPresentacion as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (DuplicatePresentacionCodigo, DuplicatePresentacionDescripcion) as e:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception:
        session.rollback()
        raise
    try:
        sync_service.synchronize_presentacion(int(row.id))
        session.commit()
    except Exception:
        session.rollback()
    return PresentacionResponse.model_validate(row)
