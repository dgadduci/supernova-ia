class ComercioNotFound(Exception):
    pass


class EstadoComercioNotFound(Exception):
    pass


class EstadoComercioInUse(Exception):
    pass


class DuplicateWhatsapp(Exception):
    pass


class DuplicateSlug(Exception):
    pass


class DuplicateEstado(Exception):
    pass


class InvalidEstado(Exception):
    pass


class MediosPagoNotFound(Exception):
    pass


class DuplicateMedioPago(Exception):
    pass


class InvalidMedioPago(Exception):
    pass


class MetodoEntregaNotFound(Exception):
    pass


class DuplicateMetodoEntrega(Exception):
    pass


class InvalidMetodoEntrega(Exception):
    pass


class CategoriaProductoNotFound(Exception):
    pass


class InvalidCategoriaProducto(Exception):
    pass


class PresentacionNotFound(Exception):
    pass


class DuplicatePresentacionCodigo(Exception):
    pass


class DuplicatePresentacionDescripcion(Exception):
    pass


class InvalidPresentacion(Exception):
    pass


class ProductoNotFound(Exception):
    pass


class DuplicateProductoNombre(Exception):
    pass


class InvalidProducto(Exception):
    pass


class ProductoPresentacionNotFound(Exception):
    pass


class PrecioNotFound(Exception):
    pass


class DuplicatePrecio(Exception):
    pass


class InvalidPrecio(Exception):
    pass


class PedidoNotFound(Exception):
    pass


class PedidoNotEditable(Exception):
    pass


class InvalidEstadoTransition(Exception):
    pass


class InvalidEstadoPedido(Exception):
    pass


class ClienteNotFound(Exception):
    pass


class InvalidWhatsApp(Exception):
    pass


class SessionNotFound(Exception):
    pass


class DuplicateActiveSession(Exception):
    pass


class SessionNotActive(Exception):
    pass


class IncompatiblePedidoAssociation(Exception):
    pass


class SessionAlreadyClosed(Exception):
    pass


class PedidoProductoNotFound(Exception):
    pass


class PedidoProductoNotEditable(Exception):
    pass


class InvalidCantidad(Exception):
    pass


class ModificationFailed(Exception):
    """Sentinel raised by `PedidoProductoService.modify_product` when an
    unexpected technical failure must be propagated to the handler as a
    deterministic `failed` outcome without rolling back the caller's
    transaction.

    The handler translates this sentinel to `processed_intent.status =
    "failed"`. Any other exception propagates unchanged so the transactional
    wrapper's `db.rollback()` is preserved.
    """

    pass


class ProductoAliasNotFound(Exception):
    pass


class InvalidProductoAlias(Exception):
    pass


class DuplicateProductoAlias(Exception):
    pass


class ProductoAliasPresentationMismatch(Exception):
    pass


class UnsafeAliasSeederMapping(Exception):
    pass


class ProductoPresentacionEmbeddingNotFound(LookupError):
    pass


class InvalidProductoPresentacionEmbedding(ValueError):
    pass


class ProductoPresentacionEmbeddingPersistenceError(Exception):
    pass


class DuplicateProductoPresentacionEmbedding(Exception):
    pass


EmbeddingNotFound = ProductoPresentacionEmbeddingNotFound
InvalidEmbedding = InvalidProductoPresentacionEmbedding
