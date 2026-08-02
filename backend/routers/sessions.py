from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as SqlSession

from backend.dependencies import get_session
from backend.schemas.session import (
    SessionCreate,
    SessionPedidoUpdate,
    SessionResponse,
)
from backend.services.exceptions import (
    DuplicateActiveSession,
    IncompatiblePedidoAssociation,
    PedidoNotFound,
    SessionAlreadyClosed,
    SessionNotActive,
    SessionNotFound,
)
from backend.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _service(session: SqlSession = Depends(get_session)) -> SessionService:
    return SessionService(session)


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    service: SessionService = Depends(_service),
) -> SessionResponse:
    try:
        row = service.create(payload.id_comercio, payload.id_cliente, payload.id_pedido)
    except DuplicateActiveSession as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return SessionResponse.model_validate(row)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session_by_id(
    session_id: int,
    service: SessionService = Depends(_service),
) -> SessionResponse:
    try:
        row = service.get_by_id(session_id)
    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SessionResponse.model_validate(row)


@router.get(
    "/comercios/{comercio_id}/clientes/{cliente_id}/activa",
    response_model=SessionResponse,
)
def get_active_session(
    comercio_id: int,
    cliente_id: int,
    service: SessionService = Depends(_service),
) -> SessionResponse:
    try:
        row = service.get_active(comercio_id, cliente_id)
    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SessionResponse.model_validate(row)


@router.patch("/{session_id}/movimiento", response_model=SessionResponse)
def update_movimiento(
    session_id: int,
    service: SessionService = Depends(_service),
) -> SessionResponse:
    try:
        row = service.update_movimiento(session_id)
    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SessionNotActive as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return SessionResponse.model_validate(row)


@router.put("/{session_id}/pedido", response_model=SessionResponse)
def asociar_pedido(
    session_id: int,
    payload: SessionPedidoUpdate,
    service: SessionService = Depends(_service),
) -> SessionResponse:
    try:
        row = service.asociar_pedido(session_id, payload.id_pedido)
    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SessionNotActive as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except IncompatiblePedidoAssociation as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return SessionResponse.model_validate(row)


@router.post("/{session_id}/cerrar", response_model=SessionResponse)
def cerrar_session(
    session_id: int,
    service: SessionService = Depends(_service),
) -> SessionResponse:
    try:
        row = service.cerrar(session_id)
    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SessionAlreadyClosed as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return SessionResponse.model_validate(row)