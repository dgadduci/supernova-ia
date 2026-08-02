from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dependencies import get_session
from backend.models import EstadoPedido
from backend.schemas.pedido import (
    PedidoCreate,
    PedidoDetalleLinea,
    PedidoDetalleResponse,
    PedidoEstadoUpdate,
    PedidoFechaEntregaUpdate,
    PedidoMedioPagoUpdate,
    PedidoMetodoEntregaUpdate,
    PedidoResponse,
)
from backend.services.exceptions import (
    InvalidEstadoPedido,
    InvalidEstadoTransition,
    MediosPagoNotFound,
    MetodoEntregaNotFound,
    PedidoNotEditable,
    PedidoNotFound,
    SessionNotActive,
    SessionNotFound,
)
from backend.services.pedido_service import PedidoService

router = APIRouter(prefix="/pedidos", tags=["pedidos"])


def _service(session: Session = Depends(get_session)) -> PedidoService:
    return PedidoService(session)


def _parse_estado(value: str) -> EstadoPedido:
    try:
        return EstadoPedido(value)
    except ValueError as e:
        raise InvalidEstadoPedido(value) from e


@router.post("", response_model=PedidoResponse, status_code=status.HTTP_201_CREATED)
def create_pedido(
    payload: PedidoCreate,
    service: PedidoService = Depends(_service),
) -> PedidoResponse:
    try:
        pedido = service.create(
            payload.id_session,
            payload.id_medio_pago,
            payload.id_metodo_entrega,
            payload.datetime_entrega_programada,
        )
    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SessionNotActive as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except MediosPagoNotFound as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except MetodoEntregaNotFound as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return PedidoResponse.model_validate(pedido)


@router.get("/{pedido_id}", response_model=PedidoResponse)
def get_pedido(
    pedido_id: int,
    service: PedidoService = Depends(_service),
) -> PedidoResponse:
    try:
        pedido = service.get_by_id(pedido_id)
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return PedidoResponse.model_validate(pedido)


@router.get("/{pedido_id}/detalle", response_model=PedidoDetalleResponse)
def get_pedido_detalle(
    pedido_id: int,
    service: PedidoService = Depends(_service),
) -> PedidoDetalleResponse:
    try:
        pedido, lineas = service.get_detalle(pedido_id)
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    detalle_lineas: list[PedidoDetalleLinea] = []
    for line in lineas:
        presentacion = line.producto_presentacion.presentacion if line.producto_presentacion is not None else None
        descripcion = presentacion.descripcion if presentacion is not None else None
        if not descripcion or not descripcion.strip():
            descripcion = "—"
        detalle_lineas.append(
            PedidoDetalleLinea(
                cantidad=line.cantidad,
                producto_nombre=line.producto_presentacion.producto.nombre,
                presentacion_descripcion=descripcion,
            )
        )
    return PedidoDetalleResponse(
        id=pedido.id,
        id_session=pedido.id_session,
        id_medio_pago=pedido.id_medio_pago,
        id_metodo_entrega=pedido.id_metodo_entrega,
        datetime_entrega_programada=pedido.datetime_entrega_programada,
        estado_pedido=pedido.estado_pedido.value,
        fecha_alta=pedido.fecha_alta,
        fecha_ultima_modificacion=pedido.fecha_ultima_modificacion,
        lineas=detalle_lineas,
    )


@router.put("/{pedido_id}/medio-pago", response_model=PedidoResponse)
def set_medio_pago(
    pedido_id: int,
    payload: PedidoMedioPagoUpdate,
    service: PedidoService = Depends(_service),
) -> PedidoResponse:
    try:
        pedido = service.set_medio_pago(pedido_id, payload.id_medio_pago)
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PedidoNotEditable as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except MediosPagoNotFound as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return PedidoResponse.model_validate(pedido)


@router.put("/{pedido_id}/metodo-entrega", response_model=PedidoResponse)
def set_metodo_entrega(
    pedido_id: int,
    payload: PedidoMetodoEntregaUpdate,
    service: PedidoService = Depends(_service),
) -> PedidoResponse:
    try:
        pedido = service.set_metodo_entrega(pedido_id, payload.id_metodo_entrega)
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PedidoNotEditable as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except MetodoEntregaNotFound as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return PedidoResponse.model_validate(pedido)


@router.put("/{pedido_id}/fecha-entrega", response_model=PedidoResponse)
def set_fecha_entrega(
    pedido_id: int,
    payload: PedidoFechaEntregaUpdate,
    service: PedidoService = Depends(_service),
) -> PedidoResponse:
    try:
        pedido = service.set_fecha_entrega(pedido_id, payload.datetime_entrega_programada)
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PedidoNotEditable as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return PedidoResponse.model_validate(pedido)


@router.put("/{pedido_id}/estado", response_model=PedidoResponse)
def cambiar_estado(
    pedido_id: int,
    payload: PedidoEstadoUpdate,
    service: PedidoService = Depends(_service),
) -> PedidoResponse:
    try:
        nuevo_estado = _parse_estado(payload.estado_pedido)
        pedido = service.cambiar_estado(pedido_id, nuevo_estado)
    except PedidoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidEstadoPedido as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except InvalidEstadoTransition as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return PedidoResponse.model_validate(pedido)