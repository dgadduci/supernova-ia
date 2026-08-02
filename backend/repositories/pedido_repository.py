from sqlalchemy.orm import Session

from backend.models import MediosPago, MetodosEntrega, Pedido


class PedidoRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, pedido_id: int) -> Pedido | None:
        return self._session.get(Pedido, pedido_id)

    def medio_pago_exists(self, medio_pago_id: int) -> bool:
        return self._session.get(MediosPago, medio_pago_id) is not None

    def metodo_entrega_exists(self, metodo_entrega_id: int) -> bool:
        return self._session.get(MetodosEntrega, metodo_entrega_id) is not None

    def add(self, pedido: Pedido) -> Pedido:
        self._session.add(pedido)
        return pedido

    def flush(self) -> None:
        self._session.flush()