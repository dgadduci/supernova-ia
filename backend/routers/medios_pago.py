from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dependencies import get_session
from backend.schemas.medios_pago import MediosPagoCreate, MediosPagoResponse
from backend.services.exceptions import (
    DuplicateMedioPago,
    InvalidMedioPago,
    MediosPagoNotFound,
)
from backend.services.medios_pago_service import MediosPagoService

router = APIRouter(prefix="/medios-pago", tags=["medios-pago"])


def _service(session: Session = Depends(get_session)) -> MediosPagoService:
    return MediosPagoService(session)


@router.get("", response_model=list[MediosPagoResponse])
def list_medios_pago(
    service: MediosPagoService = Depends(_service),
) -> list[MediosPagoResponse]:
    return [MediosPagoResponse.model_validate(m) for m in service.list_all()]


@router.get("/{medio_pago_id}", response_model=MediosPagoResponse)
def get_medio_pago(
    medio_pago_id: int,
    service: MediosPagoService = Depends(_service),
) -> MediosPagoResponse:
    try:
        return MediosPagoResponse.model_validate(service.get_by_id(medio_pago_id))
    except MediosPagoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=MediosPagoResponse, status_code=status.HTTP_201_CREATED)
def create_medio_pago(
    payload: MediosPagoCreate,
    service: MediosPagoService = Depends(_service),
) -> MediosPagoResponse:
    try:
        return MediosPagoResponse.model_validate(
            service.create(payload.codigo, payload.descripcion, payload.activo)
        )
    except InvalidMedioPago as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DuplicateMedioPago as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
