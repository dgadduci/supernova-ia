from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dependencies import get_session, require_admin_token
from backend.schemas.estado_comercio import EstadoComercioCreate, EstadoComercioResponse
from backend.services.estado_comercio_service import EstadoComercioService
from backend.services.exceptions import (
    DuplicateEstado,
    EstadoComercioNotFound,
    InvalidEstado,
)

router = APIRouter(
    prefix="/estados-comercio",
    tags=["estados-comercio"],
    dependencies=[Depends(require_admin_token)],
)


def _service(session: Session = Depends(get_session)) -> EstadoComercioService:
    return EstadoComercioService(session)


@router.get("", response_model=list[EstadoComercioResponse])
def list_estados_comercio(
    service: EstadoComercioService = Depends(_service),
) -> list[EstadoComercioResponse]:
    return [EstadoComercioResponse.model_validate(e) for e in service.list_all()]


@router.get("/{estado_comercio_id}", response_model=EstadoComercioResponse)
def get_estado_comercio(
    estado_comercio_id: int,
    service: EstadoComercioService = Depends(_service),
) -> EstadoComercioResponse:
    try:
        return EstadoComercioResponse.model_validate(service.get_by_id(estado_comercio_id))
    except EstadoComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=EstadoComercioResponse, status_code=status.HTTP_201_CREATED)
def create_estado_comercio(
    payload: EstadoComercioCreate,
    service: EstadoComercioService = Depends(_service),
) -> EstadoComercioResponse:
    try:
        return EstadoComercioResponse.model_validate(service.create(payload.estado))
    except InvalidEstado as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DuplicateEstado as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
