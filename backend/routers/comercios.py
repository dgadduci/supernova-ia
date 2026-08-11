from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dependencies import get_session, require_admin_token
from backend.schemas.comercio import ComercioCreate, ComercioResponse
from backend.services.comercio_service import ComercioService
from backend.services.exceptions import (
    ComercioNotFound,
    DuplicateSlug,
    DuplicateWhatsapp,
    EstadoComercioNotFound,
)

router = APIRouter(
    prefix="/comercios",
    tags=["comercios"],
    dependencies=[Depends(require_admin_token)],
)


def _service(session: Session = Depends(get_session)) -> ComercioService:
    return ComercioService(session)


@router.get("", response_model=list[ComercioResponse])
def list_comercios(service: ComercioService = Depends(_service)) -> list[ComercioResponse]:
    return [ComercioResponse.model_validate(c) for c in service.list_all()]


@router.get("/{comercio_id}", response_model=ComercioResponse)
def get_comercio(
    comercio_id: int, service: ComercioService = Depends(_service)
) -> ComercioResponse:
    try:
        return ComercioResponse.model_validate(service.get_by_id(comercio_id))
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=ComercioResponse, status_code=status.HTTP_201_CREATED)
def create_comercio(
    payload: ComercioCreate, service: ComercioService = Depends(_service)
) -> ComercioResponse:
    try:
        return ComercioResponse.model_validate(service.create(payload.model_dump()))
    except EstadoComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (DuplicateWhatsapp, DuplicateSlug) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

