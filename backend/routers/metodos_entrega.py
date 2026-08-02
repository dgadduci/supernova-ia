from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dependencies import get_session
from backend.schemas.metodo_entrega import MetodoEntregaCreate, MetodoEntregaResponse
from backend.services.exceptions import (
    DuplicateMetodoEntrega,
    InvalidMetodoEntrega,
    MetodoEntregaNotFound,
)
from backend.services.metodo_entrega_service import MetodoEntregaService

router = APIRouter(prefix="/metodos-entrega", tags=["metodos-entrega"])


def _service(session: Session = Depends(get_session)) -> MetodoEntregaService:
    return MetodoEntregaService(session)


@router.get("", response_model=list[MetodoEntregaResponse])
def list_metodos_entrega(
    service: MetodoEntregaService = Depends(_service),
) -> list[MetodoEntregaResponse]:
    return [MetodoEntregaResponse.model_validate(m) for m in service.list_all()]


@router.get("/{metodo_entrega_id}", response_model=MetodoEntregaResponse)
def get_metodo_entrega(
    metodo_entrega_id: int,
    service: MetodoEntregaService = Depends(_service),
) -> MetodoEntregaResponse:
    try:
        return MetodoEntregaResponse.model_validate(service.get_by_id(metodo_entrega_id))
    except MetodoEntregaNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=MetodoEntregaResponse, status_code=status.HTTP_201_CREATED)
def create_metodo_entrega(
    payload: MetodoEntregaCreate,
    service: MetodoEntregaService = Depends(_service),
) -> MetodoEntregaResponse:
    try:
        return MetodoEntregaResponse.model_validate(
            service.create(
                payload.codigo,
                payload.descripcion,
                payload.orden,
                payload.activo,
            )
        )
    except InvalidMetodoEntrega as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DuplicateMetodoEntrega as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
