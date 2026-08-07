"""Staging service for the controlled Railway fixture CLI.

The service is the only place that stages the static, deterministic
fixture catalog defined in
:mod:`backend.services.seed_controlled_railway_fixtures_data`. The CLI
is the sole owner of one setup transaction; the helpers here stage ORM
state through ``Session.add`` and never ``commit``, ``rollback``,
``begin`` or ``flush``.

The fixture catalog owns the ``estado_comercio`` table together with
the commerces, categories, presentations, products,
product-presentation associations and prices tables. The fixture
itself creates the single ``ACTIVO`` ``estado_comercio`` row it needs.
Any pre-existing row in any fixture-owned table — including a
pre-existing ``ACTIVO`` or any other pre-existing ``estado_comercio``
row — makes the namespace non-empty and produces a ``conflict``
without mutation.

The service exposes three narrow operations:

* :meth:`ControlledRailwayFixtureService.verify` — read-only
  inspection. Returns a sanitized
  :class:`FixtureApplyStatus` of ``ready`` when the exact fixture set
  already exists, ``not_ready`` when the fixture-owned catalog tables
  are empty and ``conflict`` when any pre-existing row does not match
  the fixture shape.
* :meth:`ControlledRailwayFixtureService.apply` — stages the entire
  fixture catalog in dependency order. It returns ``ready`` when the
  exact fixture set already exists (and performs no mutation),
  ``provisioned`` when it staged the full fixture set in this
  invocation and ``conflict`` when any pre-existing row blocks the
  apply.
* :meth:`ControlledRailwayFixtureService.verify_staged_dataset_is_exact` —
  called by the CLI after its single ``flush`` and before its single
  ``commit``. Returns ``True`` when the staged dataset matches the
  locked fixture shape (every fixture-owned count, identity, state,
  category, presentation, product, association and price); ``False``
  otherwise. Never mutates any row.

The service never logs, prints or returns database URLs, E.164
destinations, credentials, message bodies, signatures or raw caught
exception text. The CLI sanitizes whatever it must surface to the
operator.
"""
from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session, relationship

from backend.models import (
    CategoriaProducto,
    Comercio,
    EstadoComercio,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.services.seed_controlled_railway_fixtures_data import (
    CATEGORY_FIXTURES,
    COMMERCE_ESTADO_CODIGO,
    COMMERCE_FIXTURES,
    PRESENTATION_FIXTURES,
    PRESENTATIONS_BY_CATEGORY,
    PRICE_FIXTURES,
    PRODUCT_FIXTURES,
    expected_fixture_counts,
)


class FixtureApplyStatus(str, enum.Enum):
    """Sanitized status for both verify and apply operations.

    Each value is a safe identifier; no value exposes database URLs,
    E.164 addresses or caught exception text.
    """

    READY = "ready"
    PROVISIONED = "provisioned"
    NOT_READY = "not_ready"
    CONFLICT = "conflict"
    TECHNICAL_FAILURE = "technical_failure"


class FixtureApplyMode(str, enum.Enum):
    """CLI mode echoed in every result for evidence auditing."""

    VERIFY = "verify"
    APPLY = "apply"


@dataclass(frozen=True)
class FixtureApplyResult:
    """Sanitized outcome of a verify or apply pass.

    Every value is safe to log, print and persist in fixture evidence.
    Only numeric IDs, stable slugs, fixed counts and a sanitized
    detail marker are exposed.
    """

    mode: FixtureApplyMode
    status: FixtureApplyStatus
    counts: FixtureCounts
    comercio_ids: tuple[int, ...] = ()
    detalle: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FixtureCounts:
    """Aggregate counts the CLI prints for the operator.

    The dataclass is duplicated here so the service layer never imports
    from the static-data module just to type a result field; both
    dataclasses share the same field shape by construction.
    """

    comercios: int
    categorias: int
    presentaciones: int
    productos: int
    producto_presentaciones: int
    precios: int


_RUNTIME_RELATIONSHIPS_INSTALLED: bool = False


def _install_runtime_relationships() -> None:
    """Install transient back-reference relationships on the catalog
    mappers so the fixture service can stage ORM state without an
    intermediate ``flush``.

    The model exposes the foreign keys as plain ``Mapped[int]`` columns
    without a back-reference ``relationship`` attribute. SQLAlchemy's
    unit of work cannot detect the FK dependency from a plain integer
    column and inserts dependent rows before their parents, which
    fails the database FK constraint. The fixture CLI contract forbids
    ``flush`` in the service, so we cannot materialise parent IDs
    eagerly. Adding a transient ``relationship`` to each mapper at
    import time lets the staging code use ``cat.comercio = c`` (and
    analogous) so the unit of work resolves the dependency graph
    correctly at the single CLI ``flush`` time.
    """
    global _RUNTIME_RELATIONSHIPS_INSTALLED
    if _RUNTIME_RELATIONSHIPS_INSTALLED:
        return
    inspect(Comercio).add_property(
        "_runtime_estado",
        relationship(
            EstadoComercio,
            foreign_keys=lambda: [Comercio.estado_id],
            overlaps="estado",
        ),
    )
    inspect(CategoriaProducto).add_property(
        "_runtime_comercio",
        relationship(
            Comercio,
            foreign_keys=lambda: [CategoriaProducto.id_comercio],
        ),
    )
    inspect(Presentacion).add_property(
        "_runtime_comercio",
        relationship(
            Comercio,
            foreign_keys=lambda: [Presentacion.id_comercio],
        ),
    )
    inspect(Producto).add_property(
        "_runtime_categoria",
        relationship(
            CategoriaProducto,
            foreign_keys=lambda: [Producto.id_categoria_producto],
            overlaps="categoria,productos",
        ),
    )
    inspect(ProductoPresentacion).add_property(
        "_runtime_producto",
        relationship(
            Producto,
            foreign_keys=lambda: [ProductoPresentacion.id_producto],
            overlaps="presentaciones,producto",
        ),
    )
    inspect(ProductoPresentacion).add_property(
        "_runtime_presentacion",
        relationship(
            Presentacion,
            foreign_keys=lambda: [ProductoPresentacion.id_presentacion],
            overlaps="presentacion,productos_presentacion",
        ),
    )
    inspect(Precio).add_property(
        "_runtime_producto_presentacion",
        relationship(
            ProductoPresentacion,
            foreign_keys=lambda: [Precio.id_producto_presentacion],
            overlaps="producto_presentacion",
        ),
    )
    _RUNTIME_RELATIONSHIPS_INSTALLED = True


class ControlledRailwayFixtureService:
    """Staging-only service for the controlled Railway fixture CLI.

    The service is intentionally narrow. It only knows how to:

    * read every fixture-owned catalog table to detect pre-existing
      rows and the exact fixture set;
    * stage the static fixture dataset in dependency order through
      ``Session.add`` using transient relationship attributes so the
      CLI's single ``flush`` can resolve the FK dependency graph
      correctly.

    Transaction ownership is NEVER claimed here. The service stages
    ORM state and the CLI runs the single ``flush`` (to expose staged
    rows to the final read-back verification) followed by the single
    ``commit`` or ``rollback``.
    """

    def __init__(self, session: Session) -> None:
        _install_runtime_relationships()
        self._session = session

    def verify(self) -> FixtureApplyResult:
        """Return the read-only sanitized readiness outcome.

        The call NEVER mutates any row. It inspects every fixture-owned
        catalog table and reports:

        * ``ready`` — the exact per-comercio fixture set already
          exists, every catalog row matches the locked identity,
          state, category, presentation, product-presentation
          association and price.
        * ``not_ready`` — every catalog-owned table is empty and the
          fixture catalog has not been applied.
        * ``conflict`` — any catalog-owned table has a pre-existing
          row that does not match the exact fixture shape.
        """
        counts = expected_fixture_counts()
        owned_row_counts = self._count_catalog_rows()
        if self._is_empty_namespace(owned_row_counts):
            return FixtureApplyResult(
                mode=FixtureApplyMode.VERIFY,
                status=FixtureApplyStatus.NOT_READY,
                counts=FixtureCounts(
                    comercios=counts.comercios,
                    categorias=counts.categorias,
                    presentaciones=counts.presentaciones,
                    productos=counts.productos,
                    producto_presentaciones=counts.producto_presentaciones,
                    precios=counts.precios,
                ),
                detalle="empty_target",
            )
        if self._is_exact_fixture_set(owned_row_counts, counts):
            commerce_ids = self._existing_commerce_ids_for_slugs(
                [fixture.slug for fixture in COMMERCE_FIXTURES]
            )
            return FixtureApplyResult(
                mode=FixtureApplyMode.VERIFY,
                status=FixtureApplyStatus.READY,
                counts=FixtureCounts(
                    comercios=counts.comercios,
                    categorias=counts.categorias,
                    presentaciones=counts.presentaciones,
                    productos=counts.productos,
                    producto_presentaciones=counts.producto_presentaciones,
                    precios=counts.precios,
                ),
                comercio_ids=commerce_ids,
                detalle="exact_match",
            )
        return FixtureApplyResult(
            mode=FixtureApplyMode.VERIFY,
            status=FixtureApplyStatus.CONFLICT,
            counts=FixtureCounts(
                comercios=counts.comercios,
                categorias=counts.categorias,
                presentaciones=counts.presentaciones,
                productos=counts.productos,
                producto_presentaciones=counts.producto_presentaciones,
                precios=counts.precios,
            ),
            detalle="pre_existing_data",
        )

    def apply(self) -> FixtureApplyResult:
        """Stage the static fixture dataset without committing.

        The call returns:

        * ``ready`` when the exact fixture set already exists and
          performs no mutation;
        * ``conflict`` when any pre-existing row blocks the apply;
        * ``provisioned`` when it successfully staged every row in
          dependency order. The CLI flushes once and commits once.

        The service never calls ``commit``, ``rollback``, ``begin`` or
        ``flush``. It never logs or returns database URLs, E.164
        addresses, credentials, message bodies or caught exception
        text.
        """
        counts = expected_fixture_counts()
        owned_row_counts = self._count_catalog_rows()
        if self._is_empty_namespace(owned_row_counts):
            self._stage_fixture_dataset()
            return FixtureApplyResult(
                mode=FixtureApplyMode.APPLY,
                status=FixtureApplyStatus.PROVISIONED,
                counts=FixtureCounts(
                    comercios=counts.comercios,
                    categorias=counts.categorias,
                    presentaciones=counts.presentaciones,
                    productos=counts.productos,
                    producto_presentaciones=counts.producto_presentaciones,
                    precios=counts.precios,
                ),
                detalle="staged",
            )
        if self._is_exact_fixture_set(owned_row_counts, counts):
            commerce_ids = self._existing_commerce_ids_for_slugs(
                [fixture.slug for fixture in COMMERCE_FIXTURES]
            )
            return FixtureApplyResult(
                mode=FixtureApplyMode.APPLY,
                status=FixtureApplyStatus.READY,
                counts=FixtureCounts(
                    comercios=counts.comercios,
                    categorias=counts.categorias,
                    presentaciones=counts.presentaciones,
                    productos=counts.productos,
                    producto_presentaciones=counts.producto_presentaciones,
                    precios=counts.precios,
                ),
                comercio_ids=commerce_ids,
                detalle="exact_match",
            )
        return FixtureApplyResult(
            mode=FixtureApplyMode.APPLY,
            status=FixtureApplyStatus.CONFLICT,
            counts=FixtureCounts(
                comercios=counts.comercios,
                categorias=counts.categorias,
                presentaciones=counts.presentaciones,
                productos=counts.productos,
                producto_presentaciones=counts.producto_presentaciones,
                precios=counts.precios,
            ),
            detalle="pre_existing_data",
        )

    def staged_commerce_ids(self) -> tuple[int, ...]:
        """Read the persisted commerce numeric ids after the CLI flushes.

        The CLI is the sole owner of the single setup transaction; the
        service deliberately never flushes so the staged commerce
        rows remain invisible until the CLI flushes once. After the
        CLI flushes, this helper exposes the persisted, canonical
        numeric IDs so the CLI can echo them in the final
        ``provisioned`` result without re-running a fresh query.
        """
        slugs = [fixture.slug for fixture in COMMERCE_FIXTURES]
        return self._existing_commerce_ids_for_slugs(slugs)

    def verify_staged_dataset_is_exact(self, counts: Any) -> bool:
        """Return ``True`` when the staged dataset exactly matches the
        locked fixture shape.

        The CLI is the sole owner of the single setup transaction.
        After its single ``flush`` and before its single ``commit``
        the CLI calls this method to verify the full staged fixture
        shape using the same locked comparison the empty-namespace
        and exact-match readiness checks already use. The method
        never mutates any row and never calls ``commit``, ``rollback``,
        ``begin`` or ``flush``.

        The check covers:

        * the exact ``estado_comercio`` count (1, the fixture-owned
          ``ACTIVO`` state);
        * the exact per-table counts for the six catalog tables;
        * the per-comercio identities, ``ACTIVO`` state, the four
          categories, the seven presentations, the products per
          category, the product-presentation associations and the
          fixed prices.
        """
        owned_row_counts = self._count_catalog_rows()
        return self._is_exact_fixture_set(owned_row_counts, counts)

    def _count_catalog_rows(self) -> dict[str, int]:
        return {
            "estado_comercio": self._count(self._session, EstadoComercio),
            "comercios": self._count(self._session, Comercio),
            "categorias_productos": self._count(self._session, CategoriaProducto),
            "presentaciones": self._count(self._session, Presentacion),
            "productos": self._count(self._session, Producto),
            "producto_presentaciones": self._count(
                self._session, ProductoPresentacion
            ),
            "producto_precios": self._count(self._session, Precio),
        }

    @staticmethod
    def _count(session: Session, model: type[Any]) -> int:
        stmt = select(func.count()).select_from(model)
        return int(session.execute(stmt).scalar_one())

    def _is_empty_namespace(
        self,
        owned_row_counts: dict[str, int],
    ) -> bool:
        """Return ``True`` when every fixture-owned table is empty.

        The fixture catalog owns the ``estado_comercio`` table
        together with the commerces, categories, presentations,
        products, product-presentation associations and prices
        tables. The fixture itself creates the single ``ACTIVO``
        ``estado_comercio`` row it needs. Any pre-existing row in any
        fixture-owned table — including a pre-existing ``ACTIVO``
        state or any other pre-existing ``estado_comercio`` row —
        makes the namespace non-empty and must be reported as
        ``conflict`` without mutation.
        """
        return all(value == 0 for value in owned_row_counts.values())

    def _is_exact_fixture_set(
        self,
        owned_row_counts: dict[str, int],
        counts: Any,
    ) -> bool:
        expected = {
            "estado_comercio": 1,
            "comercios": counts.comercios,
            "categorias_productos": counts.comercios * counts.categorias,
            "presentaciones": counts.comercios * counts.presentaciones,
            "productos": counts.comercios * counts.productos,
            "producto_presentaciones": counts.comercios
            * counts.producto_presentaciones,
            "producto_precios": counts.comercios * counts.precios,
        }
        if owned_row_counts != expected:
            return False
        return self._exact_per_comercio_shape_matches(counts)

    def _exact_per_comercio_shape_matches(self, counts: Any) -> bool:
        """Verify the exact fixture shape per comercio.

        The check is strictly per-comercio and per-(commerce, catalog)
        scope. A comercio with the right counts but the wrong
        identities, state, category, presentation, product,
        association or price is ``conflict``; a category moved
        between commerces is ``conflict``; a price altered is
        ``conflict``.
        """
        slugs = [fixture.slug for fixture in COMMERCE_FIXTURES]
        slug_to_id = self._slug_to_id_map(slugs)
        if len(slug_to_id) != len(slugs):
            return False
        estado_activo_id = self._estado_activo_id_or_none()
        if estado_activo_id is None:
            return False
        for fixture in COMMERCE_FIXTURES:
            comercio_id = slug_to_id[fixture.slug]
            if not self._per_comercio_attributes_match(
                comercio_id, fixture, estado_activo_id
            ):
                return False
            if not self._per_comercio_categorias_match(
                comercio_id, counts
            ):
                return False
            if not self._per_comercio_presentaciones_match(
                comercio_id, counts
            ):
                return False
            if not self._per_comercio_productos_match(comercio_id):
                return False
            if not self._per_comercio_asociaciones_match(comercio_id):
                return False
            if not self._per_comercio_precios_match(comercio_id):
                return False
        return True

    def _per_comercio_attributes_match(
        self,
        comercio_id: int,
        fixture: Any,
        estado_activo_id: int,
    ) -> bool:
        row = self._session.get(Comercio, comercio_id)
        if row is None:
            return False
        return (
            row.nombre_fantasia == fixture.nombre_fantasia
            and row.nombre_corto == fixture.nombre_corto
            and row.razon_social == fixture.razon_social
            and row.cuit == fixture.cuit
            and row.whatsapp == fixture.whatsapp
            and row.calle == fixture.calle
            and row.numero == fixture.numero
            and row.piso_departamento == fixture.piso_departamento
            and row.localidad == fixture.localidad
            and row.provincia == fixture.provincia
            and row.codigo_postal == fixture.codigo_postal
            and row.slug == fixture.slug
            and int(row.estado_id) == estado_activo_id
        )

    def _per_comercio_categorias_match(
        self,
        comercio_id: int,
        counts: Any,
    ) -> bool:
        expected_descs = sorted(
            fixture.descripcion for fixture in CATEGORY_FIXTURES
        )
        actual_descs = sorted(
            row[0]
            for row in self._session.execute(
                select(CategoriaProducto.descripcion)
                .where(CategoriaProducto.id_comercio == comercio_id)
                .order_by(CategoriaProducto.descripcion)
            ).all()
        )
        if actual_descs != expected_descs:
            return False
        if self._count(self._session, CategoriaProducto) != counts.comercios * counts.categorias:
            pass
        return self._count_per_comercio(
            CategoriaProducto, "id_comercio", comercio_id
        ) == counts.categorias

    def _per_comercio_presentaciones_match(
        self,
        comercio_id: int,
        counts: Any,
    ) -> bool:
        expected_codigos = sorted(
            fixture.codigo for fixture in PRESENTATION_FIXTURES
        )
        actual_codigos = sorted(
            row[0]
            for row in self._session.execute(
                select(Presentacion.codigo)
                .where(Presentacion.id_comercio == comercio_id)
                .order_by(Presentacion.codigo)
            ).all()
        )
        if actual_codigos != expected_codigos:
            return False
        return self._count_per_comercio(
            Presentacion, "id_comercio", comercio_id
        ) == counts.presentaciones

    def _per_comercio_productos_match(self, comercio_id: int) -> bool:
        expected_by_categoria: dict[str, set[str]] = {}
        for product_fixture in PRODUCT_FIXTURES:
            expected_by_categoria.setdefault(
                product_fixture.category_slug, set()
            ).add(product_fixture.nombre)
        rows = list(
            self._session.execute(
                select(CategoriaProducto.descripcion, Producto.nombre)
                .join(
                    Producto,
                    Producto.id_categoria_producto == CategoriaProducto.id,
                )
                .where(CategoriaProducto.id_comercio == comercio_id)
            ).all()
        )
        actual_by_categoria: dict[str, set[str]] = {}
        for categoria, nombre in rows:
            actual_by_categoria.setdefault(
                categoria.lower() if isinstance(categoria, str) else categoria,
                set(),
            ).add(nombre)
        if set(actual_by_categoria.keys()) != set(expected_by_categoria.keys()):
            return False
        for key, expected_set in expected_by_categoria.items():
            if actual_by_categoria.get(key) != expected_set:
                return False
        return True

    def _per_comercio_asociaciones_match(self, comercio_id: int) -> bool:
        expected_associations = set()
        for product_fixture in PRODUCT_FIXTURES:
            for presentation_codigo in PRESENTATIONS_BY_CATEGORY[
                product_fixture.category_slug
            ]:
                expected_associations.add(
                    (
                        product_fixture.category_slug,
                        product_fixture.nombre,
                        presentation_codigo,
                    )
                )
        rows = list(
            self._session.execute(
                select(
                    CategoriaProducto.descripcion,
                    Producto.nombre,
                    Presentacion.codigo,
                )
                .join(
                    Producto,
                    Producto.id_categoria_producto == CategoriaProducto.id,
                )
                .join(
                    ProductoPresentacion,
                    ProductoPresentacion.id_producto == Producto.id,
                )
                .join(
                    Presentacion,
                    Presentacion.id == ProductoPresentacion.id_presentacion,
                )
                .where(CategoriaProducto.id_comercio == comercio_id)
            ).all()
        )
        actual_associations = {
            (
                categoria.lower() if isinstance(categoria, str) else categoria,
                nombre,
                codigo,
            )
            for categoria, nombre, codigo in rows
        }
        return actual_associations == expected_associations

    def _per_comercio_precios_match(self, comercio_id: int) -> bool:
        expected_prices: set[tuple[str, str, str, Decimal]] = set()
        for product_fixture in PRODUCT_FIXTURES:
            for presentation_codigo in PRESENTATIONS_BY_CATEGORY[
                product_fixture.category_slug
            ]:
                expected_prices.add(
                    (
                        product_fixture.category_slug,
                        product_fixture.nombre,
                        presentation_codigo,
                        PRICE_FIXTURES[
                            (
                                product_fixture.category_slug,
                                product_fixture.nombre,
                                presentation_codigo,
                            )
                        ],
                    )
                )
        rows = list(
            self._session.execute(
                select(
                    CategoriaProducto.descripcion,
                    Producto.nombre,
                    Presentacion.codigo,
                    Precio.precio,
                )
                .join(
                    Producto,
                    Producto.id_categoria_producto == CategoriaProducto.id,
                )
                .join(
                    ProductoPresentacion,
                    ProductoPresentacion.id_producto == Producto.id,
                )
                .join(
                    Precio,
                    Precio.id_producto_presentacion == ProductoPresentacion.id,
                )
                .join(
                    Presentacion,
                    Presentacion.id == ProductoPresentacion.id_presentacion,
                )
                .where(CategoriaProducto.id_comercio == comercio_id)
            ).all()
        )
        actual_prices = {
            (
                categoria.lower() if isinstance(categoria, str) else categoria,
                nombre,
                codigo,
                Decimal(precio),
            )
            for categoria, nombre, codigo, precio in rows
        }
        return actual_prices == expected_prices

    def _count_per_comercio(
        self,
        model: type[Any],
        foreign_key_column: str,
        comercio_id: int,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(model)
            .where(getattr(model, foreign_key_column) == comercio_id)
        )
        return int(self._session.execute(stmt).scalar_one())

    def _estado_activo_id_or_none(self) -> int | None:
        estado = self._session.execute(
            select(EstadoComercio).where(
                EstadoComercio.estado == COMMERCE_ESTADO_CODIGO
            )
        ).scalar_one_or_none()
        if estado is None:
            return None
        return cast(int, estado.id)

    def _slug_to_id_map(self, slugs: Iterable[str]) -> dict[str, int]:
        slug_list = list(slugs)
        if not slug_list:
            return {}
        rows = list(
            self._session.execute(
                select(Comercio.slug, Comercio.id).where(
                    Comercio.slug.in_(slug_list)
                )
            ).all()
        )
        return {row[0]: int(row[1]) for row in rows}

    def _existing_commerce_ids_for_slugs(
        self, slugs: Iterable[str]
    ) -> tuple[int, ...]:
        slug_to_id = self._slug_to_id_map(slugs)
        return tuple(
            slug_to_id[slug]
            for slug in slugs
            if slug in slug_to_id
        )

    def _stage_fixture_dataset(self) -> None:
        """Stage the entire fixture dataset in dependency order.

        The service stages ORM state through ``Session.add`` using
        transient back-reference relationships so the unit of work
        resolves the FK dependency graph correctly at the single CLI
        ``flush`` time. The service never calls ``flush``,
        ``commit``, ``rollback`` or ``begin``.
        """
        estado_activo = EstadoComercio(estado=COMMERCE_ESTADO_CODIGO)
        self._session.add(estado_activo)

        comercios_by_slug: dict[str, Comercio] = {}
        for commerce_fixture in COMMERCE_FIXTURES:
            comercio = Comercio(
                nombre_fantasia=commerce_fixture.nombre_fantasia,
                nombre_corto=commerce_fixture.nombre_corto,
                razon_social=commerce_fixture.razon_social,
                cuit=commerce_fixture.cuit,
                whatsapp=commerce_fixture.whatsapp,
                calle=commerce_fixture.calle,
                numero=commerce_fixture.numero,
                piso_departamento=commerce_fixture.piso_departamento,
                localidad=commerce_fixture.localidad,
                provincia=commerce_fixture.provincia,
                codigo_postal=commerce_fixture.codigo_postal,
                slug=commerce_fixture.slug,
                estado_id=0,
                _runtime_estado=estado_activo,
            )
            self._session.add(comercio)
            comercios_by_slug[commerce_fixture.slug] = comercio

        categorias_by_comercio_slug: dict[str, dict[str, CategoriaProducto]] = {}
        for commerce_fixture in COMMERCE_FIXTURES:
            comercio = comercios_by_slug[commerce_fixture.slug]
            categorias_by_comercio_slug[commerce_fixture.slug] = {}
            for category_fixture in CATEGORY_FIXTURES:
                categoria = CategoriaProducto(
                    id_comercio=0,
                    descripcion=category_fixture.descripcion,
                    activo=True,
                    orden=category_fixture.orden,
                    _runtime_comercio=comercio,
                )
                self._session.add(categoria)
                categorias_by_comercio_slug[commerce_fixture.slug][
                    category_fixture.slug
                ] = categoria

        presentaciones_by_comercio_slug: dict[
            str, dict[str, Presentacion]
        ] = {}
        for commerce_fixture in COMMERCE_FIXTURES:
            comercio = comercios_by_slug[commerce_fixture.slug]
            presentaciones_by_comercio_slug[commerce_fixture.slug] = {}
            for presentation_fixture in PRESENTATION_FIXTURES:
                presentacion = Presentacion(
                    id_comercio=0,
                    codigo=presentation_fixture.codigo,
                    descripcion=presentation_fixture.descripcion,
                    activo=True,
                    orden=presentation_fixture.orden,
                    _runtime_comercio=comercio,
                )
                self._session.add(presentacion)
                presentaciones_by_comercio_slug[commerce_fixture.slug][
                    presentation_fixture.codigo
                ] = presentacion

        for commerce_fixture in COMMERCE_FIXTURES:
            for product_fixture in PRODUCT_FIXTURES:
                categoria = categorias_by_comercio_slug[commerce_fixture.slug][
                    product_fixture.category_slug
                ]
                producto = Producto(
                    id_categoria_producto=0,
                    nombre=product_fixture.nombre,
                    descripcion=product_fixture.descripcion,
                    activo=True,
                    disponible=True,
                    orden=0,
                    _runtime_categoria=categoria,
                )
                self._session.add(producto)
                for presentation_codigo in PRESENTATIONS_BY_CATEGORY[
                    product_fixture.category_slug
                ]:
                    presentacion = (
                        presentaciones_by_comercio_slug[commerce_fixture.slug][
                            presentation_codigo
                        ]
                    )
                    association = ProductoPresentacion(
                        id_producto=0,
                        id_presentacion=0,
                        activo=True,
                        orden=0,
                        _runtime_producto=producto,
                        _runtime_presentacion=presentacion,
                    )
                    self._session.add(association)
                    precio_decimal: Decimal = PRICE_FIXTURES[
                        (
                            product_fixture.category_slug,
                            product_fixture.nombre,
                            presentation_codigo,
                        )
                    ]
                    precio = Precio(
                        id_producto_presentacion=0,
                        precio=precio_decimal,
                        _runtime_producto_presentacion=association,
                    )
                    self._session.add(precio)


def build_service(session: Session) -> ControlledRailwayFixtureService:
    """Build a fresh staging service bound to ``session``.

    Kept as a one-liner factory so tests can build the service without
    importing the class symbol directly.
    """
    return ControlledRailwayFixtureService(session)


__all__ = [
    "ControlledRailwayFixtureService",
    "FixtureApplyMode",
    "FixtureApplyResult",
    "FixtureApplyStatus",
    "FixtureCounts",
    "build_service",
]
