from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dependencies import get_session
from backend.schemas.cliente import (
    ClienteActivoUpdate,
    ClienteCreate,
    ClienteResponse,
    ClienteUpdate,
)
from backend.services.cliente_service import ClienteService
from backend.services.exceptions import (
    ClienteNotFound,
    DuplicateWhatsapp,
    InvalidWhatsApp,
)

router = APIRouter(prefix="/clientes", tags=["clientes"])


def _service(session: Session = Depends(get_session)) -> ClienteService:
    return ClienteService(session)


@router.post("", response_model=ClienteResponse, status_code=status.HTTP_201_CREATED)
def create_cliente(
    payload: ClienteCreate,
    service: ClienteService = Depends(_service),
) -> ClienteResponse:
    try:
        cliente = service.create(payload.whatsapp, payload.nombre, payload.domicilio, True)
    except InvalidWhatsApp as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except DuplicateWhatsapp as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return ClienteResponse.model_validate(cliente)


@router.get("/whatsapp/{whatsapp}", response_model=ClienteResponse)
def get_cliente_by_whatsapp(
    whatsapp: str,
    service: ClienteService = Depends(_service),
) -> ClienteResponse:
    try:
        cliente = service.get_by_whatsapp(whatsapp)
    except InvalidWhatsApp as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ClienteNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ClienteResponse.model_validate(cliente)


@router.get("/{cliente_id}", response_model=ClienteResponse)
def get_cliente(
    cliente_id: int,
    service: ClienteService = Depends(_service),
) -> ClienteResponse:
    try:
        cliente = service.get_by_id(cliente_id)
    except ClienteNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ClienteResponse.model_validate(cliente)


@router.put("/{cliente_id}", response_model=ClienteResponse)
def update_cliente(
    cliente_id: int,
    payload: ClienteUpdate,
    service: ClienteService = Depends(_service),
) -> ClienteResponse:
    try:
        cliente = service.update(cliente_id, payload.nombre, payload.domicilio, payload.activo)
    except ClienteNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ClienteResponse.model_validate(cliente)


@router.patch("/{cliente_id}/activo", response_model=ClienteResponse)
def set_cliente_activo(
    cliente_id: int,
    payload: ClienteActivoUpdate,
    service: ClienteService = Depends(_service),
) -> ClienteResponse:
    try:
        cliente = service.set_activo(cliente_id, payload.activo)
    except ClienteNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ClienteResponse.model_validate(cliente)