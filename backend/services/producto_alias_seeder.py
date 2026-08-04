"""Idempotent seeder for the active hardcoded product alias set.

Defines the product-wide alias transfer from
``backend.recognizers.product_recognizer.ALIASES_PALABRAS`` to the
``producto_aliases`` table. Each mapping uses the exact canonical product
name and a commerce scope identifier; the seeder resolves the target
product with no partial-name matching or database ID lookup.

The seeder never deletes or modifies unrelated rows. A failed required
mapping aborts the outer transaction so partial state is never persisted.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.models import (
    CategoriaProducto,
    Comercio,
    Producto,
    ProductoPresentacion,
)
from backend.services.exceptions import (
    DuplicateProductoAlias,
    InvalidProductoAlias,
    ProductoAliasPresentationMismatch,
    UnsafeAliasSeederMapping,
)
from backend.services.producto_alias_service import ProductoAliasService


@dataclass(frozen=True)
class AliasSeed:
    """One required alias mapping.

    ``comercio_nombre_corto`` selects the commerce by exact
    ``comercios.nombre_corto``. ``producto_nombre`` is the exact canonical
    product name. ``presentacion_codigo`` distinguishes presentation-specific
    aliases from product-wide ones; ``None`` means product-wide.
    """

    comercio_nombre_corto: str
    producto_nombre: str
    alias: str
    presentacion_codigo: str | None = None


MOZZARELLA_ALIASES: tuple[str, ...] = (
    "muza",
    "muzza",
    "muzarela",
    "muzarella",
    "mozarela",
    "mozarella",
    "muzzarela",
    "muzzarella",
    "musarela",
    "musarella",
)
FUGAZZETA_ALIASES: tuple[str, ...] = ("fugazeta", "fugazetta")
NAPOLITANA_ALIASES: tuple[str, ...] = ("napoli",)
CALABRESA_ALIASES: tuple[str, ...] = ("calabreza",)


CANONICAL_COMERCIO_SHORT_NAMES: tuple[str, ...] = (
    "Pizzería Don Pepe",
    "El Hornero",
    "La Napoli",
    "Sole e Luna",
    "Forno Bravo",
)


def _producto_wide_aliases() -> list[AliasSeed]:
    """Build product-wide seeds for every canonical commerce."""
    seeds: list[AliasSeed] = []
    for comercio_short in CANONICAL_COMERCIO_SHORT_NAMES:
        for alias in MOZZARELLA_ALIASES:
            seeds.append(
                AliasSeed(
                    comercio_nombre_corto=comercio_short,
                    producto_nombre="Pizza de Muzzarella",
                    alias=alias,
                )
            )
        for alias in FUGAZZETA_ALIASES:
            seeds.append(
                AliasSeed(
                    comercio_nombre_corto=comercio_short,
                    producto_nombre="Pizza Fugazzeta",
                    alias=alias,
                )
            )
        for alias in NAPOLITANA_ALIASES:
            seeds.append(
                AliasSeed(
                    comercio_nombre_corto=comercio_short,
                    producto_nombre="Pizza Napolitana",
                    alias=alias,
                )
            )
        for alias in CALABRESA_ALIASES:
            seeds.append(
                AliasSeed(
                    comercio_nombre_corto=comercio_short,
                    producto_nombre="Pizza Calabresa",
                    alias=alias,
                )
            )
    return seeds


PRODUCTO_WIDE_SEEDS: tuple[AliasSeed, ...] = tuple(_producto_wide_aliases())


@dataclass(frozen=True)
class SeederResult:
    inserted: int
    unchanged: int
    skipped: int
    failed: int
    failed_mappings: tuple[AliasSeed, ...]

    @property
    def total_required(self) -> int:
        return self.inserted + self.unchanged + self.failed


class _Resolution:
    SKIP = "skip"
    UNSAFE = "unsafe"


def _resolve_comercio(session: Session, nombre_corto: str) -> Comercio | None:
    return session.query(Comercio).filter(Comercio.nombre_corto == nombre_corto).one_or_none()


def _resolve_producto(
    session: Session,
    comercio_id: int,
    producto_nombre: str,
) -> list[Producto]:
    stmt = (
        session.query(Producto)
        .join(CategoriaProducto, Producto.id_categoria_producto == CategoriaProducto.id)
        .filter(
            CategoriaProducto.id_comercio == comercio_id,
            Producto.nombre == producto_nombre,
        )
    )
    return list(stmt.all())


def _resolve_producto_presentacion(
    session: Session,
    id_producto: int,
    presentacion_codigo: str,
) -> list[ProductoPresentacion]:
    from backend.models import Presentacion

    stmt = (
        session.query(ProductoPresentacion)
        .join(Presentacion, ProductoPresentacion.id_presentacion == Presentacion.id)
        .filter(
            ProductoPresentacion.id_producto == id_producto,
            Presentacion.codigo == presentacion_codigo,
        )
    )
    return list(stmt.all())


def _resolve_target(
    session: Session,
    seed: AliasSeed,
) -> tuple[str, tuple[Comercio, Producto, ProductoPresentacion | None] | None]:
    """Return a (status, resolution) tuple.

    Status is ``SKIP`` when the canonical commerce is not in the database
    (so the seeder quietly ignores the seed) or ``UNSAFE`` when the
    commerce exists but resolution did not produce exactly one product or
    presentation match. Any other state is ``OK`` and the resolution is
    the (comercio, producto, presentacion) tuple.
    """
    comercio = _resolve_comercio(session, seed.comercio_nombre_corto)
    if comercio is None:
        return _Resolution.SKIP, None
    productos = _resolve_producto(session, comercio.id, seed.producto_nombre)
    if len(productos) != 1:
        return _Resolution.UNSAFE, None
    presentacion: ProductoPresentacion | None = None
    if seed.presentacion_codigo is not None:
        presentaciones = _resolve_producto_presentacion(
            session, productos[0].id, seed.presentacion_codigo
        )
        if len(presentaciones) != 1:
            return _Resolution.UNSAFE, None
        presentacion = presentaciones[0]
    return "ok", (comercio, productos[0], presentacion)


def run_seeder(
    session: Session,
    seeds: Iterable[AliasSeed] = PRODUCTO_WIDE_SEEDS,
) -> SeederResult:
    """Run the seeder within ``session``.

    The caller owns the transaction. ``run_seeder`` MUST NOT call
    ``commit``, ``rollback``, ``close``, or ``begin``. A failed required
    mapping raises ``UnsafeAliasSeederMapping`` so the caller can roll
    back the outer transaction.
    """
    service = ProductoAliasService(session)
    inserted = 0
    unchanged = 0
    skipped = 0
    failed: list[AliasSeed] = []
    seed_list = list(seeds)
    for seed in seed_list:
        try:
            status, resolution = _resolve_target(session, seed)
        except Exception as exc:
            raise UnsafeAliasSeederMapping(
                f"failed required mapping {seed}: {exc}"
            ) from exc
        if status == _Resolution.SKIP:
            skipped += 1
            continue
        if status == _Resolution.UNSAFE or resolution is None:
            raise UnsafeAliasSeederMapping(
                f"unsafe ownership for required seed {seed}: "
                f"zero or multiple product/presentation matches"
            )
        _comercio, producto, presentacion = resolution
        id_producto_presentacion = (
            presentacion.id if presentacion is not None else None
        )
        before = service._repo.find_same_scope(
            producto.id,
            id_producto_presentacion,
            service.normalize(seed.alias),
            include_inactive=True,
        )
        try:
            service.ensure(
                id_producto=producto.id,
                alias=seed.alias,
                id_producto_presentacion=id_producto_presentacion,
            )
        except (InvalidProductoAlias, DuplicateProductoAlias, ProductoAliasPresentationMismatch) as exc:
            raise UnsafeAliasSeederMapping(
                f"failed required mapping {seed}: {exc}"
            ) from exc
        if before is None:
            inserted += 1
        else:
            unchanged += 1
    return SeederResult(
        inserted=inserted,
        unchanged=unchanged,
        skipped=skipped,
        failed=len(failed),
        failed_mappings=tuple(failed),
    )


__all__ = [
    "CALABRESA_ALIASES",
    "CANONICAL_COMERCIO_SHORT_NAMES",
    "FUGAZZETA_ALIASES",
    "MOZZARELLA_ALIASES",
    "NAPOLITANA_ALIASES",
    "PRODUCTO_WIDE_SEEDS",
    "AliasSeed",
    "SeederResult",
    "run_seeder",
]
