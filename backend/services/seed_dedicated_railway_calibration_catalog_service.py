"""Staging service for the dedicated Railway calibration catalog CLI.

The service is the only place that stages the static, deterministic
calibration catalog defined in
:mod:`backend.services.seed_dedicated_railway_calibration_catalog_data`.
The CLI is the sole owner of one setup transaction; the helpers
here stage ORM state through ``Session.add`` and never ``commit``,
``rollback``, ``begin`` or ``flush``.

The catalog owns the same fixture-owned tables as the pilot fixture:
``estado_comercio``, ``comercios``, ``categorias_productos``,
``presentaciones``, ``productos``, ``producto_presentaciones`` and
``producto_precios``. The catalog itself creates the single
``ACTIVO`` ``estado_comercio`` row it needs.

The service refuses to operate unless the target exposes the
non-secret dedicated marker
(``RAILWAY_CALIBRATION_CATALOG_TARGET=dedicated``). The marker is
validated by the CLI before any service call; the service
double-checks the marker invariant so a unit test can never bypass
it. The CLI never compares URLs, hosts, credentials or any other
sensitive value.

The service exposes three narrow operations:

* :meth:`DedicatedRailwayCalibrationCatalogService.verify` —
  read-only inspection. Returns ``ready`` when the exact catalog is
  already present, ``not_ready`` when every fixture-owned table is
  empty, ``conflict`` when any pre-existing row does not match the
  catalog shape, and ``target_marker_missing`` /
  ``target_marker_mismatch`` when the dedicated marker is absent or
  wrong.
* :meth:`DedicatedRailwayCalibrationCatalogService.apply` —
  stages the entire catalog in dependency order. Returns ``ready``
  when the exact catalog already exists and performs no mutation,
  ``provisioned`` when it staged the full catalog set in this
  invocation, ``conflict`` when any pre-existing row blocks the
  apply, and ``target_marker_missing`` /
  ``target_marker_mismatch`` when the marker guard rejects the
  destination.
* :meth:`DedicatedRailwayCalibrationCatalogService.verify_staged_dataset_is_exact`
  — called by the CLI after its single ``flush`` and before its
  single ``commit``. Returns ``True`` when the staged catalog
  matches the locked catalog shape (every fixture-owned count,
  identity, state, category, presentation, product-presentation
  association, price and manifest coverage). ``False`` otherwise.
  Never mutates any row.

The service never logs, prints or returns database URLs, E.164
destinations, credentials, message bodies, signatures, raw caught
exception text or any other sensitive value. The CLI sanitises
whatever it must surface to the operator.
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
from backend.models.estado_comercio import EstadoComercioModoOperacion
from backend.services.seed_dedicated_railway_calibration_catalog_data import (
    CATEGORY_FIXTURES,
    COMMERCE_ESTADO_CODIGO,
    COMMERCE_ESTADO_MODO,
    COMMERCE_FIXTURES,
    DEDICATED_COMMERCE_SLUG,
    DEDICATED_TARGET_ENV_VAR,
    DEDICATED_TARGET_MARKER,
    PRESENTATION_FIXTURES,
    PRESENTATIONS_BY_CATEGORY,
    PRICE_FIXTURES,
    PRODUCT_FIXTURES,
    audit_manifest_coverage,
    expected_fixture_counts,
)


class CatalogApplyStatus(str, enum.Enum):
    """Sanitized status for both verify and apply operations.

    Each value is a safe identifier; no value exposes database URLs,
    E.164 addresses or caught exception text.
    """

    READY = "ready"
    PROVISIONED = "provisioned"
    NOT_READY = "not_ready"
    CONFLICT = "conflict"
    TARGET_MARKER_MISSING = "target_marker_missing"
    TARGET_MARKER_MISMATCH = "target_marker_mismatch"
    TECHNICAL_FAILURE = "technical_failure"


class CatalogApplyMode(str, enum.Enum):
    """CLI mode echoed in every result for evidence auditing."""

    VERIFY = "verify"
    APPLY = "apply"


@dataclass(frozen=True)
class CatalogApplyResult:
    """Sanitized outcome of a verify or apply pass.

    Every value is safe to log, print and persist in catalog
    evidence. Only numeric IDs, stable slugs, fixed counts and a
    sanitized detail marker are exposed.
    """

    mode: CatalogApplyMode
    status: CatalogApplyStatus
    counts: CatalogCounts
    comercio_ids: tuple[int, ...] = ()
    detalle: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogCounts:
    """Aggregate counts the CLI prints for the operator.

    The dataclass is duplicated here so the service layer never
    imports from the static-data module just to type a result field;
    both dataclasses share the same field shape by construction.
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

    The model exposes the foreign keys as plain ``Mapped[int]``
    columns without a back-reference ``relationship`` attribute.
    SQLAlchemy's unit of work cannot detect the FK dependency from a
    plain integer column and inserts dependent rows before their
    parents, which fails the database FK constraint. The CLI contract
    forbids ``flush`` in the service, so we cannot materialise parent
    IDs eagerly. Adding a transient ``relationship`` to each mapper
    at import time lets the staging code use ``cat.comercio = c`` (and
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


class DedicatedRailwayCalibrationCatalogService:
    """Staging-only service for the dedicated Railway calibration catalog CLI.

    The service is intentionally narrow. It only knows how to:

    * read every fixture-owned catalog table to detect pre-existing
      rows and the exact catalog set;
    * stage the static catalog dataset in dependency order through
      ``Session.add`` using transient relationship attributes so the
      CLI's single ``flush`` can resolve the FK dependency graph
      correctly.

    Transaction ownership is NEVER claimed here. The service stages
    ORM state and the CLI runs the single ``flush`` (to expose
    staged rows to the final read-back verification) followed by
    the single ``commit`` or ``rollback``.
    """

    _DEDICATED_SLUG = DEDICATED_COMMERCE_SLUG

    def __init__(self, session: Session) -> None:
        _install_runtime_relationships()
        self._session = session

    def verify(
        self,
        *,
        target_marker: str | None,
        expected_marker: str,
    ) -> CatalogApplyResult:
        """Return the read-only sanitized readiness outcome.

        The call NEVER mutates any row. The marker is validated
        first; missing or mismatched marker yields
        ``target_marker_missing`` / ``target_marker_mismatch``
        without touching the database. With a valid marker the
        service inspects every fixture-owned catalog table and
        reports:

        * ``ready`` — the exact per-commerce catalog set already
          exists, every catalog row matches the locked identity,
          state, category, presentation, product-presentation
          association and price;
        * ``not_ready`` — every catalog-owned table is empty and the
          catalog has not been applied;
        * ``conflict`` — any catalog-owned table has a pre-existing
          row that does not match the exact catalog shape.
        """
        marker_result = self._evaluate_target_marker(
            target_marker=target_marker,
            expected_marker=expected_marker,
        )
        if marker_result is not None:
            return marker_result

        counts = expected_fixture_counts()
        owned_row_counts = self._count_catalog_rows()
        if self._is_empty_namespace(owned_row_counts):
            return CatalogApplyResult(
                mode=CatalogApplyMode.VERIFY,
                status=CatalogApplyStatus.NOT_READY,
                counts=self._counts_to_catalog(counts),
                detalle="empty_target",
            )
        if self._is_exact_catalog_set(owned_row_counts, counts):
            commerce_ids = self._existing_commerce_ids_for_slugs(
                [fixture.slug for fixture in COMMERCE_FIXTURES]
            )
            return CatalogApplyResult(
                mode=CatalogApplyMode.VERIFY,
                status=CatalogApplyStatus.READY,
                counts=self._counts_to_catalog(counts),
                comercio_ids=commerce_ids,
                detalle="exact_match",
            )
        return CatalogApplyResult(
            mode=CatalogApplyMode.VERIFY,
            status=CatalogApplyStatus.CONFLICT,
            counts=self._counts_to_catalog(counts),
            detalle="pre_existing_data",
        )

    def apply(
        self,
        *,
        target_marker: str | None,
        expected_marker: str,
    ) -> CatalogApplyResult:
        """Stage the static catalog dataset without committing.

        The call returns:

        * ``target_marker_missing`` / ``target_marker_mismatch``
          when the marker guard rejects the destination — no mutation
          occurs;
        * ``ready`` when the exact catalog set already exists and
          performs no mutation;
        * ``conflict`` when any pre-existing row blocks the apply;
        * ``provisioned`` when it successfully staged every row in
          dependency order. The CLI flushes once and commits once.

        The service never calls ``commit``, ``rollback``, ``begin``
        or ``flush``. It never logs or returns database URLs, E.164
        addresses, credentials, message bodies or caught exception
        text.
        """
        marker_result = self._evaluate_target_marker(
            target_marker=target_marker,
            expected_marker=expected_marker,
        )
        if marker_result is not None:
            marker_result = CatalogApplyResult(
                mode=CatalogApplyMode.APPLY,
                status=marker_result.status,
                counts=marker_result.counts,
                comercio_ids=marker_result.comercio_ids,
                detalle=marker_result.detalle,
                extra=marker_result.extra,
            )
            return marker_result

        counts = expected_fixture_counts()
        owned_row_counts = self._count_catalog_rows()
        if self._is_empty_namespace(owned_row_counts):
            self._stage_catalog_dataset()
            return CatalogApplyResult(
                mode=CatalogApplyMode.APPLY,
                status=CatalogApplyStatus.PROVISIONED,
                counts=self._counts_to_catalog(counts),
                detalle="staged",
            )
        if self._is_exact_catalog_set(owned_row_counts, counts):
            commerce_ids = self._existing_commerce_ids_for_slugs(
                [fixture.slug for fixture in COMMERCE_FIXTURES]
            )
            return CatalogApplyResult(
                mode=CatalogApplyMode.APPLY,
                status=CatalogApplyStatus.READY,
                counts=self._counts_to_catalog(counts),
                comercio_ids=commerce_ids,
                detalle="exact_match",
            )
        return CatalogApplyResult(
            mode=CatalogApplyMode.APPLY,
            status=CatalogApplyStatus.CONFLICT,
            counts=self._counts_to_catalog(counts),
            detalle="pre_existing_data",
        )

    def staged_commerce_ids(self) -> tuple[int, ...]:
        """Read the persisted commerce numeric ids after the CLI flushes.

        The CLI is the sole owner of the single setup transaction;
        the service deliberately never flushes so the staged
        commerce rows remain invisible until the CLI flushes once.
        After the CLI flushes, this helper exposes the persisted,
        canonical numeric IDs so the CLI can echo them in the final
        ``provisioned`` result without re-running a fresh query.
        """
        slugs = [fixture.slug for fixture in COMMERCE_FIXTURES]
        return self._existing_commerce_ids_for_slugs(slugs)

    def verify_staged_dataset_is_exact(self, counts: Any) -> bool:
        """Return ``True`` when the staged dataset exactly matches the
        locked catalog shape.

        The CLI is the sole owner of the single setup transaction.
        After its single ``flush`` and before its single ``commit``
        the CLI calls this method to verify the full staged catalog
        shape using the same locked comparison the empty-namespace
        and exact-match readiness checks already use. The method
        never mutates any row and never calls ``commit``,
        ``rollback``, ``begin`` or ``flush``.

        The check covers:

        * the exact ``estado_comercio`` count (1, the catalog-owned
          ``ACTIVO`` state);
        * the exact per-table counts for the six catalog tables;
        * the per-commerce identities, ``ACTIVO`` state, the four
          categories, the seven presentations, the products per
          category, the product-presentation associations, the
          fixed prices and the manifest coverage.
        """
        owned_row_counts = self._count_catalog_rows()
        if not self._is_exact_catalog_set(owned_row_counts, counts):
            return False
        audit = audit_manifest_coverage()
        if audit["missing_tokens"] != 0 or audit["ambiguous_tokens"] != 0:
            return False
        return audit["covered_tokens"] == audit["manifest_tokens"]

    def _evaluate_target_marker(
        self,
        *,
        target_marker: str | None,
        expected_marker: str,
    ) -> CatalogApplyResult | None:
        if target_marker is None:
            return CatalogApplyResult(
                mode=CatalogApplyMode.VERIFY,
                status=CatalogApplyStatus.TARGET_MARKER_MISSING,
                counts=CatalogCounts(0, 0, 0, 0, 0, 0),
                detalle="target_marker_missing",
            )
        if target_marker != expected_marker:
            return CatalogApplyResult(
                mode=CatalogApplyMode.VERIFY,
                status=CatalogApplyStatus.TARGET_MARKER_MISMATCH,
                counts=CatalogCounts(0, 0, 0, 0, 0, 0),
                detalle="target_marker_mismatch",
            )
        return None

    @staticmethod
    def _counts_to_catalog(counts: Any) -> CatalogCounts:
        return CatalogCounts(
            comercios=counts.comercios,
            categorias=counts.categorias,
            presentaciones=counts.presentaciones,
            productos=counts.productos,
            producto_presentaciones=counts.producto_presentaciones,
            precios=counts.precios,
        )

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

        The catalog owns the ``estado_comercio`` table together with
        the commerces, categories, presentations, products,
        product-presentation associations and prices tables. The
        catalog itself creates the single ``ACTIVO``
        ``estado_comercio`` row it needs. Any pre-existing row in any
        fixture-owned table — including a pre-existing ``ACTIVO``
        state or any other pre-existing ``estado_comercio`` row —
        makes the namespace non-empty and must be reported as
        ``conflict`` without mutation.
        """
        return all(value == 0 for value in owned_row_counts.values())

    def _is_exact_catalog_set(
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
        """Verify the exact catalog shape per comercio."""
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
            if not self._per_comercio_categorias_match(comercio_id, counts):
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
                EstadoComercio.codigo == COMMERCE_ESTADO_CODIGO
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

    def _stage_catalog_dataset(self) -> None:
        """Stage the entire catalog dataset in dependency order.

        The service stages ORM state through ``Session.add`` using
        transient back-reference relationships so the unit of work
        resolves the FK dependency graph correctly at the single CLI
        ``flush`` time. The service never calls ``flush``,
        ``commit``, ``rollback`` or ``begin``.
        """
        estado_activo = EstadoComercio(
            codigo=COMMERCE_ESTADO_CODIGO,
            descripcion=COMMERCE_ESTADO_CODIGO,
            modo_operacion=EstadoComercioModoOperacion(COMMERCE_ESTADO_MODO),
            seleccionable=True,
        )
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

        categorias_by_comercio_slug: dict[
            str, dict[str, CategoriaProducto]
        ] = {}
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


def build_service(session: Session) -> DedicatedRailwayCalibrationCatalogService:
    """Build a fresh staging service bound to ``session``.

    Kept as a one-liner factory so tests can build the service
    without importing the class symbol directly.
    """
    return DedicatedRailwayCalibrationCatalogService(session)


__all__ = [
    "CatalogApplyMode",
    "CatalogApplyResult",
    "CatalogApplyStatus",
    "CatalogCounts",
    "DedicatedRailwayCalibrationCatalogService",
    "build_service",
]
