"""Shared application operations for catalog and flavor creates.

This module is the single application boundary for the catalog
(category, product, presentation, price) and flavor-assignment create
operations. The JSON API routers and the browser administrative panel
both call this service so the post-create embedding synchronization,
the commit / rollback sequence and the exact transaction ownership
are defined once and never duplicated.

The service is deliberately a thin orchestrator over the existing
``CategoriaProductoService``, ``ProductoService``,
``PresentacionService``, ``PrecioService`` and
``ComunicacionFlavorService``. It does NOT redefine domain validation
or own commit / rollback semantics — the existing services and the
embedded ``CatalogEmbeddingSynchronizationService`` are the
authority. The service only owns the call ordering so the routers
and the panel cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy.orm import Session

from backend.config.settings import Settings
from backend.llm.embedding_client import (
    EmbeddingClientProtocol,
    OllamaEmbeddingClient,
)
from backend.models import (
    CategoriaProducto,
    Comercio,
    Precio,
    Presentacion,
    Producto,
)
from backend.services.categoria_producto_service import CategoriaProductoService
from backend.services.catalog_embedding_synchronization_service import (
    CatalogEmbeddingSynchronizationService,
)
from backend.services.comercio_service import ComercioService
from backend.services.comunicacion_flavor_service import (
    ComunicacionFlavorService,
)
from backend.services.precio_service import PrecioService
from backend.services.presentacion_service import PresentacionService
from backend.services.producto_service import ProductoService


class CatalogCreateEmbeddingClientFactory(Protocol):
    """Factory protocol for the embedding client used by the
    post-create synchronization step.

    The factory is intentionally minimal: it accepts the loaded
    :class:`Settings` and returns an
    :class:`EmbeddingClientProtocol`. Tests inject a stub factory so
    no real Ollama call is made during the panel's focused test
    suite.
    """

    def __call__(self, settings: Settings) -> EmbeddingClientProtocol: ...


def _default_embedding_client_factory(settings: Settings) -> EmbeddingClientProtocol:
    return OllamaEmbeddingClient(settings)


@dataclass(frozen=True)
class CatalogCreateResult:
    """Returned to the caller after a successful catalog or flavor create.

    The dataclass surfaces the persisted ORM row only. Internal
    metadata (the embedding synchronization outcome, the commit /
    rollback sequence, any environment details) is intentionally
    absent so the routers and the panel cannot accidentally leak it.
    """

    row: object


class CatalogCreateService:
    """Single application boundary for the catalog and flavor creates.

    Every method matches the existing JSON router contract exactly:

    * ``create_categoria_producto`` commits the category row, runs the
      post-create embedding synchronization through the existing
      :class:`CatalogEmbeddingSynchronizationService`, commits the
      synchronization transaction on success and rolls back on a
      synchronization failure. Domain failures raise before any
      commit and the caller is responsible for the rollback.
    * ``create_producto`` mirrors the same pattern for the product
      scope and the product-level ``synchronize_producto`` call.
    * ``create_presentacion`` mirrors the same pattern for the
      presentation scope.
    * ``create_precio`` defers entirely to :class:`PrecioService`,
      which already owns its commit / rollback semantics and does
      not require embedding synchronization.
    * ``assign_flavor`` mirrors the existing flavor router's
      commit / rollback sequence: assign through the existing
      service, fetch the refreshed commerce and commit once.

    The service never calls ``commit`` / ``rollback`` / ``flush`` /
    ``refresh`` / ``begin`` / ``close`` outside the documented
    boundaries. It never reads configuration files, never logs and
    never inspects the database beyond the existing services. The
    caller-owned transaction remains the contract; the service
    borrows the caller's session for the whole orchestration.

    Tests inject ``flavor_service`` (and the other domain services)
    so the existing router tests can continue to spy on the legacy
    service contract without going through this orchestrator.
    """

    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        embedding_client_factory: CatalogCreateEmbeddingClientFactory | None = None,
        categoria_service: CategoriaProductoService | None = None,
        producto_service: ProductoService | None = None,
        presentacion_service: PresentacionService | None = None,
        precio_service: PrecioService | None = None,
        flavor_service: ComunicacionFlavorService | None = None,
        comercio_service: ComercioService | None = None,
        sync_service: CatalogEmbeddingSynchronizationService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        factory = embedding_client_factory or _default_embedding_client_factory
        self._embedding_client = factory(settings)
        self._categoria_service = categoria_service or CategoriaProductoService(session)
        self._producto_service = producto_service or ProductoService(session)
        self._presentacion_service = presentacion_service or PresentacionService(session)
        self._precio_service = precio_service or PrecioService(session)
        self._flavor_service = flavor_service or ComunicacionFlavorService(session)
        self._comercio_service = comercio_service or ComercioService(session)
        self._sync_service = sync_service or CatalogEmbeddingSynchronizationService(
            session=session,
            embedding_client=self._embedding_client,
            settings=settings,
        )

    def create_categoria_producto(
        self,
        comercio_id: int,
        descripcion: str,
        activo: bool | None,
        orden: int | None,
    ) -> CategoriaProducto:
        """Commit a category and synchronize its embedding scope.

        Mirrors :func:`backend.routers.categorias_productos.create_categoria_producto`
        exactly: commit the category row first, then run the
        post-create embedding synchronization and commit on success
        or roll back on a synchronization failure. Domain
        validation failures raise before any commit.
        """
        try:
            row = self._categoria_service.create(
                comercio_id,
                descripcion,
                activo,
                orden,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        try:
            self._sync_service.synchronize_categoria(int(row.id))
            self._session.commit()
        except Exception:
            self._session.rollback()
        return row

    def create_producto(
        self,
        categoria_producto_id: int,
        nombre: str,
        descripcion: str | None,
        activo: bool | None,
        disponible: bool | None,
        orden: int | None,
    ) -> Producto:
        """Commit a product and synchronize its embedding scope.

        Mirrors :func:`backend.routers.productos.create_producto`
        exactly.
        """
        try:
            row = self._producto_service.create(
                categoria_producto_id,
                nombre,
                descripcion,
                activo,
                disponible,
                orden,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        try:
            self._sync_service.synchronize_producto(int(row.id))
            self._session.commit()
        except Exception:
            self._session.rollback()
        return row

    def create_presentacion(
        self,
        comercio_id: int,
        codigo: str,
        descripcion: str,
        activo: bool | None,
        orden: int | None,
    ) -> Presentacion:
        """Commit a presentation and synchronize its embedding scope.

        Mirrors :func:`backend.routers.presentaciones.create_presentacion`
        exactly.
        """
        try:
            row = self._presentacion_service.create(
                comercio_id,
                codigo,
                descripcion,
                activo,
                orden,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        try:
            self._sync_service.synchronize_presentacion(int(row.id))
            self._session.commit()
        except Exception:
            self._session.rollback()
        return row

    def create_precio(
        self,
        producto_presentacion_id: int,
        precio: Decimal,
    ) -> Precio:
        """Create a price row through the existing service.

        Mirrors :func:`backend.routers.precios.create_precio` exactly.
        The existing service owns its commit / rollback semantics, so
        this helper only forwards the call.
        """
        return self._precio_service.create(producto_presentacion_id, precio)

    def assign_flavor(
        self,
        comercio_id: int,
        flavor_id: int | None,
    ) -> tuple[Comercio, object]:
        """Assign or clear the flavor for one comercio.

        Mirrors :func:`backend.routers.flavors_comunicacion.assign_flavor_comunicacion`
        exactly. The flavor service flushes the assignment; the
        caller-owned transaction commits the assignment once the
        refreshed commerce has been re-read. Domain validation
        failures roll the session back before the call returns so
        the caller never observes a half-applied state.
        """
        try:
            self._flavor_service.assign_to_comercio(comercio_id, flavor_id)
        except Exception:
            self._session.rollback()
            raise
        comercio = self._comercio_service.get_by_id(comercio_id)
        self._session.commit()
        return comercio, comercio.flavor_comunicacion


__all__ = [
    "CatalogCreateEmbeddingClientFactory",
    "CatalogCreateResult",
    "CatalogCreateService",
]