from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.dependencies import get_session, require_admin_token
from backend.schemas.estado_comercio import EstadoComercioResponse
from backend.services.estado_comercio_service import EstadoComercioService
from backend.services.exceptions import EstadoComercioNotFound

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


__all__ = ["router"]