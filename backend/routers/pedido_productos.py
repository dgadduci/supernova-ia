from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as SqlSession

from backend.dependencies import get_session
from backend.schemas.pedido_producto import (
    PedidoProductoCreate,
    PedidoProductoResponse,
    PedidoProductoUpdate,
)
from backend.services.exceptions import (
    PedidoNotFound,
    PedidoProductoNotEditable,
    PedidoProductoNotFound,
    PrecioNotFound,
    ProductoPresentacionNotFound,
)
from backend.services.pedido_producto_service import PedidoProductoService

router = APIRouter(tags=["pedidos-productos"])


def _service(session: SqlSession = Depends(get_session)) -> PedidoProductoService:
    return PedidoProductoService(session)


@router.post(
    "/pedidos/{pedido_id}/productos",
    response_model=PedidoProductoResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_pedido_producto(
    pedido_id: int,
    payload: PedidoProductoCreate,
    service: PedidoProductoService = Depends(_service),
) -> PedidoProductoResponse:
    try:
        item = service.add(
            pedido_id,
            payload.id_producto_presentacion,
            payload.cantidad,
            payload.observaciones,
        )
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PedidoProductoNotEditable as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ProductoPresentacionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PrecioNotFound as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return PedidoProductoResponse.model_validate(item)


@router.get(
    "/pedidos/{pedido_id}/productos",
    response_model=list[PedidoProductoResponse],
)
def list_pedido_productos(
    pedido_id: int,
    service: PedidoProductoService = Depends(_service),
) -> list[PedidoProductoResponse]:
    try:
        items = service.list_by_pedido(pedido_id)
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [PedidoProductoResponse.model_validate(i) for i in items]


@router.get(
    "/pedidos-productos/{item_id}",
    response_model=PedidoProductoResponse,
)
def get_pedido_producto(
    item_id: int,
    service: PedidoProductoService = Depends(_service),
) -> PedidoProductoResponse:
    try:
        item = service.get_by_id(item_id)
    except PedidoProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return PedidoProductoResponse.model_validate(item)


@router.put(
    "/pedidos-productos/{item_id}",
    response_model=PedidoProductoResponse,
)
def update_pedido_producto(
    item_id: int,
    payload: PedidoProductoUpdate,
    service: PedidoProductoService = Depends(_service),
) -> PedidoProductoResponse:
    try:
        item = service.update(item_id, payload.cantidad, payload.observaciones)
    except PedidoProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PedidoProductoNotEditable as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return PedidoProductoResponse.model_validate(item)


@router.delete(
    "/pedidos-productos/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_pedido_producto(
    item_id: int,
    service: PedidoProductoService = Depends(_service),
) -> None:
    try:
        service.delete(item_id)
    except PedidoProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PedidoProductoNotEditable as e:
        raise HTTPException(status_code=409, detail=str(e)) from e