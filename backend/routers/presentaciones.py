from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dependencies import get_session
from backend.schemas.presentacion import PresentacionCreate, PresentacionResponse
from backend.services.exceptions import (
    ComercioNotFound,
    DuplicatePresentacionCodigo,
    DuplicatePresentacionDescripcion,
    InvalidPresentacion,
    PresentacionNotFound,
)
from backend.services.presentacion_service import PresentacionService

router = APIRouter(tags=["presentaciones"])


def _service(session: Session = Depends(get_session)) -> PresentacionService:
    return PresentacionService(session)


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
    service: PresentacionService = Depends(_service),
) -> PresentacionResponse:
    try:
        return PresentacionResponse.model_validate(
            service.create(
                comercio_id,
                payload.codigo,
                payload.descripcion,
                payload.activo,
                payload.orden,
            )
        )
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidPresentacion as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (DuplicatePresentacionCodigo, DuplicatePresentacionDescripcion) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
