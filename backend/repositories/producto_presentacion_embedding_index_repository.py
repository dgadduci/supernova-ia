"""Commerce-scoped catalog projection for the per-document indexer.

Subphase 4.6 introduces a per-document indexer that walks every
applicable ``producto_presentacion`` (active and inactive), loads the
parent catalog chain and the applicable aliases, and hands the
projection to the pure ``ProductEmbeddingDocumentBuilder``. The
projection repository is the only place that touches SQL for the
catalog scan; the indexer is intentionally infrastructure-thin.

Two-query strategy: one query for the projection rows (eager-loaded
parent chain), one query for the alias map. No N+1.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.embeddings import (
    ProductEmbeddingAliasInput,
)
from backend.models import (
    CategoriaProducto,
    Presentacion,
    Producto,
    ProductoAlias,
    ProductoPresentacion,
)


@dataclass(frozen=True)
class PresentationBundle:
    """One catalog projection row for the indexer.

    Carries the catalog projection DTOs, the applicable alias list, and
    the parent ``activo`` flags so the indexer can detect inactive
    catalog chains before any embedding work.
    """

    producto_id: int
    producto_presentacion_id: int
    producto_nombre: str
    producto_descripcion: str | None
    categoria_nombre: str
    presentacion_id: int
    presentacion_codigo: str
    presentacion_descripcion: str
    producto_activo: bool
    categoria_producto_activo: bool
    presentacion_activo: bool
    producto_presentacion_activo: bool
    aliases: tuple[ProductEmbeddingAliasInput, ...] = field(default=())

    def is_inactive(self) -> bool:
        return not (
            self.producto_activo
            and self.categoria_producto_activo
            and self.presentacion_activo
            and self.producto_presentacion_activo
        )


class ProductoPresentacionEmbeddingIndexRepository:
    """Consumer-neutral commerce-scoped catalog projection."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_presentations(
        self,
        *,
        id_comercio: int | None,
        id_producto: int | None,
        id_producto_presentacion: int | None,
    ) -> list[PresentationBundle]:
        stmt = (
            select(ProductoPresentacion)
            .join(Producto, ProductoPresentacion.id_producto == Producto.id)
            .join(
                CategoriaProducto,
                Producto.id_categoria_producto == CategoriaProducto.id,
            )
            .join(
                Presentacion,
                ProductoPresentacion.id_presentacion == Presentacion.id,
            )
            .options(
                joinedload(ProductoPresentacion.producto).joinedload(
                    Producto.categoria
                ),
                joinedload(ProductoPresentacion.presentacion),
            )
        )
        if id_comercio is not None:
            stmt = stmt.where(CategoriaProducto.id_comercio == id_comercio)
        if id_producto is not None:
            stmt = stmt.where(Producto.id == id_producto)
        if id_producto_presentacion is not None:
            stmt = stmt.where(ProductoPresentacion.id == id_producto_presentacion)
        rows = list(self._session.execute(stmt).scalars())
        if not rows:
            return []
        pp_ids = sorted(row.id for row in rows)
        product_ids = sorted({row.id_producto for row in rows})
        aliases = self._load_aliases(pp_ids, product_ids)
        bundles: list[PresentationBundle] = []
        for row in rows:
            bundle = self._to_bundle(row, aliases.get(row.id, ()))
            bundles.append(bundle)
        return bundles

    def _load_aliases(
        self,
        id_producto_presentacion_values: list[int],
        id_producto_values: list[int],
    ) -> dict[int, tuple[ProductEmbeddingAliasInput, ...]]:
        if not id_producto_presentacion_values:
            return {}
        from sqlalchemy import or_

        stmt = select(ProductoAlias).where(ProductoAlias.activo.is_(True))
        if id_producto_values:
            stmt = stmt.where(
                or_(
                    (
                        ProductoAlias.id_producto_presentacion.is_(None)
                        & ProductoAlias.id_producto.in_(id_producto_values)
                    ),
                    ProductoAlias.id_producto_presentacion.in_(
                        id_producto_presentacion_values
                    ),
                )
            )
        else:
            stmt = stmt.where(
                ProductoAlias.id_producto_presentacion.in_(
                    id_producto_presentacion_values
                )
            )
        rows = list(self._session.execute(stmt).scalars())
        pp_ids_set = set(id_producto_presentacion_values)
        product_ids_set = set(id_producto_values)
        applicable: dict[int, list[ProductEmbeddingAliasInput]] = {
            pp_id: [] for pp_id in id_producto_presentacion_values
        }
        for alias in rows:
            if alias.id_producto_presentacion is None:
                if alias.id_producto not in product_ids_set:
                    continue
                target_pp_ids = [
                    pid for pid in pp_ids_set if pid in applicable
                ]
            else:
                target_pp_ids = [alias.id_producto_presentacion]
            for pid in target_pp_ids:
                if pid in applicable:
                    applicable[pid].append(
                        ProductEmbeddingAliasInput(
                            id=alias.id,
                            alias=alias.alias,
                            alias_normalizado=alias.alias_normalizado,
                            scope=(
                                "product_presentacion"
                                if alias.id_producto_presentacion is not None
                                else "product"
                            ),
                            activo=alias.activo,
                            id_producto_presentacion=alias.id_producto_presentacion,
                        )
                    )
        return {
            pid: tuple(values) for pid, values in applicable.items()
        }

    @staticmethod
    def _to_bundle(
        row: ProductoPresentacion,
        aliases: tuple[ProductEmbeddingAliasInput, ...],
    ) -> PresentationBundle:
        producto: Producto = row.producto
        categoria: CategoriaProducto = producto.categoria
        presentacion: Presentacion = row.presentacion
        return PresentationBundle(
            producto_id=producto.id,
            producto_presentacion_id=row.id,
            producto_nombre=producto.nombre,
            producto_descripcion=producto.descripcion,
            categoria_nombre=categoria.descripcion,
            presentacion_id=presentacion.id,
            presentacion_codigo=presentacion.codigo,
            presentacion_descripcion=presentacion.descripcion,
            producto_activo=bool(producto.activo),
            categoria_producto_activo=bool(categoria.activo),
            presentacion_activo=bool(presentacion.activo),
            producto_presentacion_activo=bool(row.activo),
            aliases=aliases,
        )

    # -- Scope-resolution reads (Subphase 4.8) --------------------------------
    #
    # The synchronization service uses these methods to resolve the
    # narrowest valid embedding scope for each catalog mutation. The
    # methods are intentionally read-only:
    #
    # - They MUST NOT call ``session.commit``, ``session.rollback``,
    #   ``session.close``, or ``session.begin``.
    # - They MUST NOT issue ``INSERT``, ``UPDATE``, or ``DELETE``
    #   statements.
    # - They MUST use bounded ``select()`` queries (no eager loading of
    #   unrelated collections, no full ``ProductoPresentacion`` row).

    def list_producto_presentacion_ids_by_producto(
        self, id_producto: int
    ) -> list[int]:
        """Return ids of every ``producto_presentacion`` of one producto."""
        stmt = select(ProductoPresentacion.id).where(
            ProductoPresentacion.id_producto == id_producto
        )
        return [int(row) for row in self._session.execute(stmt).scalars()]

    def list_producto_presentacion_ids_by_categoria(
        self, id_categoria: int
    ) -> list[int]:
        """Return ids of every ``producto_presentacion`` whose parent
        producto belongs to the given categoria."""
        stmt = (
            select(ProductoPresentacion.id)
            .join(Producto, ProductoPresentacion.id_producto == Producto.id)
            .where(Producto.id_categoria_producto == id_categoria)
        )
        return [int(row) for row in self._session.execute(stmt).scalars()]

    def list_producto_presentacion_ids_by_presentacion(
        self, id_presentacion: int
    ) -> list[int]:
        """Return ids of every ``producto_presentacion`` referencing the
        given presentacion."""
        stmt = select(ProductoPresentacion.id).where(
            ProductoPresentacion.id_presentacion == id_presentacion
        )
        return [int(row) for row in self._session.execute(stmt).scalars()]

    def list_producto_presentacion_ids_by_alias(
        self, id_alias: int
    ) -> list[int]:
        """Return ids of the ``producto_presentacion`` rows affected by
        the given alias.

        For presentation-specific aliases the result contains the single
        ``id_producto_presentacion`` of the alias. For product-wide
        aliases the result contains every ``producto_presentacion`` of
        the alias's ``id_producto``.

        The caller is responsible for choosing between the alias
        resolution and the captured-scope resolution for post-delete
        synchronization. This method never resolves an alias that has
        been deleted because it is invoked only while the alias row
        still exists (create / update text / activate / deactivate
        paths); the post-delete path uses the captured scope.
        """
        stmt = select(ProductoAlias).where(ProductoAlias.id == id_alias)
        alias = self._session.execute(stmt).scalar_one_or_none()
        if alias is None:
            return []
        if alias.id_producto_presentacion is not None:
            return [int(alias.id_producto_presentacion)]
        return self.list_producto_presentacion_ids_by_producto(
            int(alias.id_producto)
        )


__all__ = [
    "PresentationBundle",
    "ProductoPresentacionEmbeddingIndexRepository",
]
