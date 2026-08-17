"""Read-only projection service for the administrative catalog panel.

The service is the panel's only path into the database. It reads the
data the panel needs without ever mutating any row and without
owning commit / rollback semantics — the request-level dependency
remains the transaction owner. Every read is bounded by the
exact ``comercio_id`` (or nested) id so the panel can never
silently leak across commerces.

The service intentionally mirrors the structure of the pilot order
view service so the panel can rely on the same kind of typed
dataclasses: each method returns a frozen view model with the
documented closed fields only.
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.admin.views import (
    CatalogCategoriaDetailView,
    CatalogCategoriaRow,
    CatalogPresentacionRow,
    CatalogProductoDetailView,
    CatalogProductoPresentacionRow,
    CatalogProductoRow,
    CommerceCatalogNavigationView,
    CommerceDeliveryActiveCandidate,
    CommerceDetailView,
    CommercePaymentActiveCandidate,
    CommerceSummary,
    DeliveryMethodDetailView,
    FlavorOption,
    FlavorSummaryView,
    GlobalMedioPagoRow,
    GlobalMetodoEntregaRow,
    InactiveDeliveryMethodDetailView,
    InactivePaymentMethodDetailView,
    PaymentMethodDetailView,
)
from backend.models import (
    CategoriaProducto,
    Comercio,
    ComercioMedioPago,
    ComercioMetodoEntrega,
    MediosPago,
    MetodosEntrega,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.services.comunicacion_flavor_service import ComunicacionFlavorService


class AdministrativeCatalogPanelViewService:
    """Read-only projection over the data the administrative panel needs.

    The service does NOT call ``commit`` / ``rollback`` / ``flush`` /
    ``refresh`` / ``begin`` / ``close``. It does NOT mutate any row.
    It does NOT widen queries across commerces. It does NOT read the
    LLM, the embeddings service, the outbox or the worker state.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_comercios(self) -> list[CommerceSummary]:
        stmt = (
            select(Comercio)
            .options(joinedload(Comercio.flavor_comunicacion))
            .order_by(Comercio.id.asc())
        )
        comercios = list(self._session.execute(stmt).scalars().unique().all())
        summaries: list[CommerceSummary] = []
        for comercio in comercios:
            flavor = comercio.flavor_comunicacion
            summaries.append(
                CommerceSummary(
                    id=comercio.id,
                    nombre_fantasia=comercio.nombre_fantasia,
                    nombre_corto=comercio.nombre_corto,
                    estado=str(comercio.estado.estado) if comercio.estado else "",
                    flavor_codigo=(flavor.codigo if flavor is not None else None),
                    flavor_nombre=(flavor.nombre if flavor is not None else None),
                    tiene_flavor=flavor is not None,
                )
            )
        return summaries

    def get_commerce_detail(self, comercio_id: int) -> CommerceDetailView | None:
        stmt = (
            select(Comercio)
            .where(Comercio.id == comercio_id)
            .options(
                joinedload(Comercio.estado),
                joinedload(Comercio.flavor_comunicacion),
                selectinload(Comercio.medios_pago).joinedload(
                    ComercioMedioPago.medio_pago
                ),
                selectinload(Comercio.metodos_entrega).joinedload(
                    ComercioMetodoEntrega.metodo_entrega
                ),
            )
        )
        comercio = self._session.execute(stmt).scalar_one_or_none()
        if comercio is None:
            return None

        medios_pago: list[PaymentMethodDetailView] = []
        medios_pago_inactivos: list[InactivePaymentMethodDetailView] = []
        associated_medio_pago_ids: set[int] = set()
        for association in sorted(
            comercio.medios_pago, key=lambda item: item.id
        ):
            medio = association.medio_pago
            codigo = str(medio.codigo) if medio is not None else ""
            descripcion = (
                str(medio.descripcion) if medio is not None else ""
            )
            if medio is not None:
                associated_medio_pago_ids.add(int(medio.id))
            if medio is not None and bool(medio.activo):
                medios_pago.append(
                    PaymentMethodDetailView(
                        association_id=int(association.id),
                        medio_pago_id=int(medio.id),
                        codigo=codigo,
                        descripcion=descripcion,
                        activo=association.activo,
                        titular=association.titular,
                        alias=association.alias,
                    )
                )
            else:
                medios_pago_inactivos.append(
                    InactivePaymentMethodDetailView(
                        id=association.id,
                        codigo=codigo,
                        descripcion=descripcion,
                        titular=association.titular,
                        alias=association.alias,
                    )
                )

        metodos_entrega: list[DeliveryMethodDetailView] = []
        metodos_entrega_inactivos: list[InactiveDeliveryMethodDetailView] = []
        associated_metodo_entrega_ids: set[int] = set()
        for association in sorted(
            comercio.metodos_entrega,
            key=lambda item: (item.orden, item.id),
        ):
            metodo = association.metodo_entrega
            codigo = str(metodo.codigo) if metodo is not None else ""
            descripcion = (
                str(metodo.descripcion) if metodo is not None else ""
            )
            if metodo is not None:
                associated_metodo_entrega_ids.add(int(metodo.id))
            if metodo is not None and bool(metodo.activo):
                metodos_entrega.append(
                    DeliveryMethodDetailView(
                        association_id=int(association.id),
                        metodo_entrega_id=int(metodo.id),
                        codigo=codigo,
                        descripcion=descripcion,
                        activo=association.activo,
                        orden=association.orden,
                    )
                )
            else:
                metodos_entrega_inactivos.append(
                    InactiveDeliveryMethodDetailView(
                        id=association.id,
                        codigo=codigo,
                        descripcion=descripcion,
                        orden=association.orden,
                    )
                )

        medios_pago_candidates: list[CommercePaymentActiveCandidate] = []
        for global_row in self._session.execute(
            select(MediosPago)
            .where(MediosPago.activo.is_(True))
            .order_by(MediosPago.id.asc())
        ).scalars():
            if int(global_row.id) in associated_medio_pago_ids:
                continue
            medios_pago_candidates.append(
                CommercePaymentActiveCandidate(
                    id=int(global_row.id),
                    codigo=str(global_row.codigo),
                    descripcion=str(global_row.descripcion),
                    habilita_titular=bool(global_row.habilita_titular),
                    habilita_alias=bool(global_row.habilita_alias),
                )
            )

        metodos_entrega_candidates: list[
            CommerceDeliveryActiveCandidate
        ] = []
        for global_row in self._session.execute(
            select(MetodosEntrega)
            .where(MetodosEntrega.activo.is_(True))
            .order_by(MetodosEntrega.orden.asc(), MetodosEntrega.id.asc())
        ).scalars():
            if int(global_row.id) in associated_metodo_entrega_ids:
                continue
            metodos_entrega_candidates.append(
                CommerceDeliveryActiveCandidate(
                    id=int(global_row.id),
                    codigo=str(global_row.codigo),
                    descripcion=str(global_row.descripcion),
                    orden=int(global_row.orden),
                )
            )

        flavor: FlavorSummaryView | None = None
        if comercio.flavor_comunicacion is not None:
            flavor_row = comercio.flavor_comunicacion
            flavor = FlavorSummaryView(
                id=flavor_row.id,
                codigo=flavor_row.codigo,
                nombre=flavor_row.nombre,
                descripcion=flavor_row.descripcion,
                version=flavor_row.version,
                activo=flavor_row.activo,
            )

        return CommerceDetailView(
            id=comercio.id,
            nombre_fantasia=comercio.nombre_fantasia,
            nombre_corto=comercio.nombre_corto,
            razon_social=comercio.razon_social,
            cuit=comercio.cuit,
            whatsapp=comercio.whatsapp,
            calle=comercio.calle,
            numero=comercio.numero,
            piso_departamento=comercio.piso_departamento,
            localidad=comercio.localidad,
            provincia=comercio.provincia,
            codigo_postal=comercio.codigo_postal,
            slug=comercio.slug,
            estado=str(comercio.estado.estado) if comercio.estado else "",
            zona_horaria=comercio.zona_horaria,
            moneda=comercio.moneda,
            idioma=comercio.idioma,
            medios_pago=medios_pago,
            metodos_entrega=metodos_entrega,
            medios_pago_candidates=medios_pago_candidates,
            metodos_entrega_candidates=metodos_entrega_candidates,
            medios_pago_inactivos=medios_pago_inactivos,
            metodos_entrega_inactivos=metodos_entrega_inactivos,
            flavor=flavor,
        )

    def list_active_flavors(self) -> list[FlavorOption]:
        """List the active flavor options for the assignment form.

        The panel uses the options to populate the ``<select>``
        widget. The listing never returns inactive flavors and never
        exposes ``instruccion_llm``; the view model is the only
        surface the panel reads.
        """
        flavor_service = ComunicacionFlavorService(self._session)
        options: list[FlavorOption] = []
        for flavor in flavor_service.list_active_flavors():
            options.append(
                FlavorOption(
                    id=flavor.id,
                    codigo=flavor.codigo,
                    nombre=flavor.nombre,
                    descripcion=flavor.descripcion,
                    version=flavor.version,
                )
            )
        return options

    def get_commerce_catalog_navigation(
        self,
        comercio_id: int,
    ) -> CommerceCatalogNavigationView | None:
        """Return the commerce-scoped catalog navigation view.

        The view lists the categories and presentations that belong
        to the selected commerce and no other. Categories are
        returned in the documented ordering; presentations follow
        their own ordering. The service never reads other comercios
        and never raises if a nested id belongs to a different
        comercio — the panel hides those rows so the operator can
        never accidentally use them.
        """
        comercio = self._session.get(Comercio, comercio_id)
        if comercio is None:
            return None

        categoria_stmt = (
            select(CategoriaProducto)
            .where(CategoriaProducto.id_comercio == comercio_id)
            .order_by(
                CategoriaProducto.orden.asc(), CategoriaProducto.id.asc()
            )
        )
        categorias = list(self._session.execute(categoria_stmt).scalars())

        presentacion_stmt = (
            select(Presentacion)
            .where(Presentacion.id_comercio == comercio_id)
            .order_by(Presentacion.orden.asc(), Presentacion.id.asc())
        )
        presentaciones = list(self._session.execute(presentacion_stmt).scalars())

        return CommerceCatalogNavigationView(
            comercio_id=comercio_id,
            categorias=[
                CatalogCategoriaRow(
                    id=row.id,
                    descripcion=row.descripcion,
                    activo=row.activo,
                    orden=row.orden,
                )
                for row in categorias
            ],
            presentaciones=[
                CatalogPresentacionRow(
                    id=row.id,
                    codigo=row.codigo,
                    descripcion=row.descripcion,
                    activo=row.activo,
                    orden=row.orden,
                )
                for row in presentaciones
            ],
        )

    def get_categoria_detail(
        self,
        categoria_producto_id: int,
        *,
        expected_comercio_id: int,
    ) -> CatalogCategoriaDetailView | None:
        """Return the category detail scoped to ``expected_comercio_id``.

        The panel calls this with the parent ``comercio_id`` from
        the URL so a stale id cannot leak a foreign category into the
        form. The lookup is intentionally a no-match (returns
        ``None``) when the stored category does not belong to the
        selected commerce; the panel renders a generic not-found
        page rather than the foreign category.
        """
        stmt = (
            select(CategoriaProducto)
            .where(CategoriaProducto.id == categoria_producto_id)
            .options(joinedload(CategoriaProducto.productos))
        )
        categoria = self._session.execute(stmt).scalar_one_or_none()
        if categoria is None:
            return None
        if categoria.id_comercio != expected_comercio_id:
            return None
        productos = sorted(categoria.productos, key=lambda item: (item.orden, item.id))
        return CatalogCategoriaDetailView(
            id=categoria.id,
            id_comercio=categoria.id_comercio,
            descripcion=categoria.descripcion,
            activo=categoria.activo,
            orden=categoria.orden,
            productos=[
                CatalogProductoRow(
                    id=producto.id,
                    nombre=producto.nombre,
                    descripcion=producto.descripcion,
                    activo=producto.activo,
                    disponible=producto.disponible,
                    orden=producto.orden,
                )
                for producto in productos
            ],
        )

    def get_producto_detail(
        self,
        producto_id: int,
        *,
        expected_categoria_id: int,
        expected_comercio_id: int,
    ) -> CatalogProductoDetailView | None:
        """Return the product detail with the parent-commerce guard.

        The view is the single source of truth for the price-creation
        form: it includes only the presentations that belong to the
        selected product, and only the presentations that share the
        expected commerce scope so the form cannot offer a foreign
        presentation as a parent.
        """
        stmt = (
            select(Producto)
            .where(Producto.id == producto_id)
            .options(
                joinedload(Producto.categoria),
                joinedload(Producto.presentaciones).joinedload(
                    ProductoPresentacion.presentacion
                ),
            )
        )
        producto = self._session.execute(stmt).scalar_one_or_none()
        if producto is None:
            return None
        if producto.id_categoria_producto != expected_categoria_id:
            return None
        if producto.categoria is None:
            return None
        if producto.categoria.id_comercio != expected_comercio_id:
            return None

        presentaciones = sorted(
            producto.presentaciones, key=lambda item: (item.orden, item.id)
        )

        precio_counts: dict[int, int] = {pp.id: 0 for pp in presentaciones}
        if precio_counts:
            precio_stmt = (
                select(Precio.id_producto_presentacion, func.count())
                .where(
                    Precio.id_producto_presentacion.in_(precio_counts.keys())
                )
                .group_by(Precio.id_producto_presentacion)
            )
            for pp_id, count in self._session.execute(precio_stmt).all():
                precio_counts[int(pp_id)] = int(count)

        rows: list[CatalogProductoPresentacionRow] = []
        for pp in presentaciones:
            presentacion = pp.presentacion
            if presentacion is None:
                continue
            if presentacion.id_comercio != expected_comercio_id:
                continue
            rows.append(
                CatalogProductoPresentacionRow(
                    id=pp.id,
                    id_producto=pp.id_producto,
                    id_presentacion=pp.id_presentacion,
                    presentacion_descripcion=presentacion.descripcion,
                    precio_disponible=precio_counts.get(pp.id, 0) == 1,
                )
            )

        return CatalogProductoDetailView(
            id=producto.id,
            id_categoria_producto=producto.id_categoria_producto,
            nombre=producto.nombre,
            descripcion=producto.descripcion,
            activo=producto.activo,
            disponible=producto.disponible,
            orden=producto.orden,
            presentaciones=rows,
        )

    def find_producto_presentacion(
        self,
        producto_presentacion_id: int,
        *,
        expected_comercio_id: int,
    ) -> CatalogProductoPresentacionRow | None:
        """Return the single ``producto_presentacion`` for the price form.

        The lookup scopes strictly to the selected commerce: a row
        that links a foreign ``Producto`` or ``Presentacion`` is
        silently rejected so the panel cannot render a price form
        for a foreign resource.
        """
        stmt = (
            select(ProductoPresentacion)
            .where(ProductoPresentacion.id == producto_presentacion_id)
            .options(
                joinedload(ProductoPresentacion.producto).joinedload(
                    Producto.categoria
                ),
                joinedload(ProductoPresentacion.presentacion),
            )
        )
        association = self._session.execute(stmt).scalar_one_or_none()
        if association is None:
            return None
        if association.producto is None or association.producto.categoria is None:
            return None
        if association.producto.categoria.id_comercio != expected_comercio_id:
            return None
        if association.presentacion is None:
            return None
        if association.presentacion.id_comercio != expected_comercio_id:
            return None

        precio_count = self._session.execute(
            select(func.count())
            .select_from(Precio)
            .where(Precio.id_producto_presentacion == producto_presentacion_id)
        ).scalar_one()

        return CatalogProductoPresentacionRow(
            id=association.id,
            id_producto=association.id_producto,
            id_presentacion=association.id_presentacion,
            presentacion_descripcion=association.presentacion.descripcion,
            precio_disponible=int(precio_count) == 1,
        )

    def find_producto_presentacion_for_pp(
        self,
        *,
        producto_id: int,
        presentacion_id: int,
        expected_comercio_id: int,
    ) -> CatalogProductoPresentacionRow | None:
        """Resolve the ``ProductoPresentacion`` by ``(producto, presentacion)``.

        The helper exists because the panel's price-creation form
        receives ``producto_id`` and ``presentacion_id`` from the
        URL and must look up the canonical
        ``producto_presentacion.id`` it has to forward to the shared
        :class:`CatalogCreateService`. The lookup enforces the
        commerce isolation contract: a foreign pair returns
        ``None`` so the panel cannot submit a price for a foreign
        scope.
        """
        stmt = (
            select(ProductoPresentacion)
            .where(ProductoPresentacion.id_producto == producto_id)
            .where(ProductoPresentacion.id_presentacion == presentacion_id)
            .options(
                joinedload(ProductoPresentacion.producto).joinedload(
                    Producto.categoria
                ),
                joinedload(ProductoPresentacion.presentacion),
            )
        )
        association = self._session.execute(stmt).scalar_one_or_none()
        if association is None:
            return None
        if association.producto is None or association.producto.categoria is None:
            return None
        if association.producto.categoria.id_comercio != expected_comercio_id:
            return None
        if association.presentacion is None:
            return None
        if association.presentacion.id_comercio != expected_comercio_id:
            return None

        precio_count = self._session.execute(
            select(func.count())
            .select_from(Precio)
            .where(Precio.id_producto_presentacion == association.id)
        ).scalar_one()

        return CatalogProductoPresentacionRow(
            id=association.id,
            id_producto=association.id_producto,
            id_presentacion=association.id_presentacion,
            presentacion_descripcion=association.presentacion.descripcion,
            precio_disponible=int(precio_count) == 1,
        )

    def find_comercio_presentaciones(
        self,
        comercio_id: int,
    ) -> Iterable[Presentacion]:
        """Yield the presentations that belong to ``comercio_id``.

        The helper is exposed for the product-create form so the
        template can advertise the parent's available
        presentations; the helper never widens the query.
        """
        stmt = (
            select(Presentacion)
            .where(Presentacion.id_comercio == comercio_id)
            .order_by(Presentacion.orden.asc(), Presentacion.id.asc())
        )
        return list(self._session.execute(stmt).scalars())

    def find_comercio_categorias(
        self,
        comercio_id: int,
    ) -> Iterable[CategoriaProducto]:
        """Yield the categories that belong to ``comercio_id``."""
        stmt = (
            select(CategoriaProducto)
            .where(CategoriaProducto.id_comercio == comercio_id)
            .order_by(CategoriaProducto.orden.asc(), CategoriaProducto.id.asc())
        )
        return list(self._session.execute(stmt).scalars())

    def list_global_medios_pago(self) -> list[GlobalMedioPagoRow]:
        """Return the global ``MediosPago`` catalog for the panel.

        The helper reads the canonical global catalog (every row,
        not filtered by comercio) and projects each row into a
        closed :class:`GlobalMedioPagoRow` view so the panel can
        render the global availability flags without ever inspecting
        SQLAlchemy ORM state. The helper does NOT read
        ``ComercioMedioPago`` and never widens the query to a
        comercio scope.
        """
        stmt = select(MediosPago).order_by(MediosPago.id.asc())
        rows = list(self._session.execute(stmt).scalars())
        return [
            GlobalMedioPagoRow(
                id=row.id,
                codigo=str(row.codigo),
                descripcion=str(row.descripcion),
                activo=bool(row.activo),
                habilita_titular=bool(row.habilita_titular),
                habilita_alias=bool(row.habilita_alias),
            )
            for row in rows
        ]

    def get_global_medio_pago(
        self, medio_pago_id: int
    ) -> GlobalMedioPagoRow | None:
        """Return the single global ``MediosPago`` row or ``None``.

        The helper is intentionally a no-match (returns ``None``)
        for an unknown id so the panel renders the documented
        not-found page rather than propagating a raw exception.
        The helper does NOT read ``ComercioMedioPago`` and never
        exposes per-commerce ``titular`` / ``alias`` values.
        """
        row = self._session.get(MediosPago, medio_pago_id)
        if row is None:
            return None
        return GlobalMedioPagoRow(
            id=row.id,
            codigo=str(row.codigo),
            descripcion=str(row.descripcion),
            activo=bool(row.activo),
            habilita_titular=bool(row.habilita_titular),
            habilita_alias=bool(row.habilita_alias),
        )

    def get_global_metodo_entrega(
        self, metodo_entrega_id: int
    ) -> GlobalMetodoEntregaRow | None:
        row = self._session.get(MetodosEntrega, metodo_entrega_id)
        if row is None:
            return None
        return GlobalMetodoEntregaRow(
            id=int(row.id),
            codigo=str(row.codigo),
            descripcion=str(row.descripcion),
            orden=int(row.orden),
            activo=bool(row.activo),
        )

    def get_commerce_payment_configuration(
        self,
        *,
        comercio_id: int,
        medio_pago_id: int,
    ):
        """Return the scoped payment configuration view for a form.

        The lookup is the single panel entry point for the
        per-commerce payment form: it merges the global
        ``MediosPago`` row with the existing ``ComercioMedioPago``
        bridge row and returns a closed
        :class:`PaymentMethodConfigurationView`. The helper refuses
        to return a row for a foreign ``comercio_id`` so a forged
        POST cannot reach a different comercio's association.
        """
        from backend.admin.views import PaymentMethodConfigurationView

        global_row = self._session.get(MediosPago, medio_pago_id)
        if global_row is None:
            return None

        stmt = (
            select(ComercioMedioPago)
            .where(ComercioMedioPago.id_comercio == comercio_id)
            .where(ComercioMedioPago.id_medio_pago == medio_pago_id)
        )
        bridge = self._session.execute(stmt).scalar_one_or_none()
        if bridge is None:
            return PaymentMethodConfigurationView(
                association_id=0,
                codigo=str(global_row.codigo),
                descripcion=str(global_row.descripcion),
                activo=False,
                titular=None,
                alias=None,
                habilita_titular=bool(global_row.habilita_titular),
                habilita_alias=bool(global_row.habilita_alias),
            )
        if bridge.id_comercio != comercio_id:
            return None
        return PaymentMethodConfigurationView(
            association_id=bridge.id,
            codigo=str(global_row.codigo),
            descripcion=str(global_row.descripcion),
            activo=bool(bridge.activo),
            titular=bridge.titular,
            alias=bridge.alias,
            habilita_titular=bool(global_row.habilita_titular),
            habilita_alias=bool(global_row.habilita_alias),
        )

    def get_commerce_delivery_configuration(
        self,
        *,
        comercio_id: int,
        metodo_entrega_id: int,
    ):
        """Return the scoped delivery configuration view for a form.

        The lookup mirrors the payment configuration helper:
        it merges the global ``MetodosEntrega`` row with the
        existing ``ComercioMetodoEntrega`` bridge row and returns
        a closed :class:`DeliveryMethodConfigurationView`. The
        helper refuses to return a row for a foreign
        ``comercio_id`` so a forged POST cannot reach a different
        comercio's association.
        """
        from backend.admin.views import DeliveryMethodConfigurationView

        global_row = self._session.get(MetodosEntrega, metodo_entrega_id)
        if global_row is None:
            return None

        stmt = (
            select(ComercioMetodoEntrega)
            .where(ComercioMetodoEntrega.id_comercio == comercio_id)
            .where(ComercioMetodoEntrega.id_metodo_entrega == metodo_entrega_id)
        )
        bridge = self._session.execute(stmt).scalar_one_or_none()
        if bridge is None:
            return DeliveryMethodConfigurationView(
                association_id=0,
                codigo=str(global_row.codigo),
                descripcion=str(global_row.descripcion),
                activo=False,
                orden=0,
                global_orden=int(global_row.orden),
            )
        if bridge.id_comercio != comercio_id:
            return None
        return DeliveryMethodConfigurationView(
            association_id=bridge.id,
            codigo=str(global_row.codigo),
            descripcion=str(global_row.descripcion),
            activo=bool(bridge.activo),
            orden=int(bridge.orden),
            global_orden=int(global_row.orden),
        )


__all__ = ["AdministrativeCatalogPanelViewService"]