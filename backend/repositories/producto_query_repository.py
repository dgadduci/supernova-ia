from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.models import (
    CategoriaProducto,
    Presentacion,
    Precio,
    Producto,
    ProductoPresentacion,
)


class ProductoQueryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_detalle(self, producto_id: int) -> Producto | None:
        stmt = (
            select(Producto)
            .where(Producto.id == producto_id)
            .options(
                joinedload(Producto.categoria),
                selectinload(Producto.presentaciones)
                .joinedload(ProductoPresentacion.presentacion),
                selectinload(Producto.presentaciones).joinedload(
                    ProductoPresentacion.precios
                ),
            )
        )
        producto = self._session.execute(stmt).scalar_one_or_none()
        if producto is not None:
            producto.presentaciones.sort(
                key=lambda association: (association.orden, association.id)
            )
        return producto

    def list_presentaciones_by_ids(
        self,
        producto_presentacion_ids: list[int],
    ) -> list[ProductoPresentacion]:
        if not producto_presentacion_ids:
            return []
        stmt = (
            select(ProductoPresentacion)
            .where(ProductoPresentacion.id.in_(producto_presentacion_ids))
            .options(
                joinedload(ProductoPresentacion.producto).joinedload(Producto.categoria),
                joinedload(ProductoPresentacion.presentacion),
            )
        )
        return list(self._session.execute(stmt).scalars())

    def list_presentaciones(self, producto_id: int) -> list[ProductoPresentacion] | None:
        exists = self._session.get(Producto, producto_id) is not None
        if not exists:
            return None
        stmt = (
            select(ProductoPresentacion)
            .where(ProductoPresentacion.id_producto == producto_id)
            .options(
                joinedload(ProductoPresentacion.presentacion),
                selectinload(ProductoPresentacion.precios),
            )
            .order_by(ProductoPresentacion.orden, ProductoPresentacion.id)
        )
        return list(self._session.execute(stmt).scalars())

    def get_asociacion(
        self,
        producto_id: int,
        presentacion_id: int,
    ) -> ProductoPresentacion | None:
        stmt = (
            select(ProductoPresentacion)
            .where(
                ProductoPresentacion.id_producto == producto_id,
                ProductoPresentacion.id_presentacion == presentacion_id,
            )
            .options(
                joinedload(ProductoPresentacion.presentacion),
                selectinload(ProductoPresentacion.precios),
            )
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_precios(self, producto_id: int) -> list[Precio] | None:
        exists = self._session.get(Producto, producto_id) is not None
        if not exists:
            return None
        stmt = (
            select(Precio)
            .join(ProductoPresentacion, Precio.id_producto_presentacion == ProductoPresentacion.id)
            .where(ProductoPresentacion.id_producto == producto_id)
            .order_by(ProductoPresentacion.orden, ProductoPresentacion.id)
        )
        return list(self._session.execute(stmt).scalars())

    def list_catalogo(
        self,
        comercio_id: int,
        solo_activos: bool,
        solo_disponibles: bool,
    ) -> list[CategoriaProducto] | None:
        if not self._session.get(Presentacion, 0) and not self._session.get(
            CategoriaProducto, 0
        ):
            exists = self._session.execute(
                select(CategoriaProducto.id).where(
                    CategoriaProducto.id_comercio == comercio_id
                )
            ).first()
        else:
            exists = self._session.execute(
                select(CategoriaProducto.id).where(
                    CategoriaProducto.id_comercio == comercio_id
                )
            ).first()
        if not exists:
            return None
        category_stmt = (
            select(CategoriaProducto)
            .where(CategoriaProducto.id_comercio == comercio_id)
            .order_by(CategoriaProducto.orden, CategoriaProducto.id)
        )
        if solo_activos:
            category_stmt = category_stmt.where(CategoriaProducto.activo.is_(True))
        categories = list(self._session.execute(category_stmt).scalars())
        for category in categories:
            self._populate_category_products(category, solo_activos, solo_disponibles)
        return categories

    def _populate_category_products(
        self,
        category: CategoriaProducto,
        solo_activos: bool,
        solo_disponibles: bool,
    ) -> None:
        product_stmt = (
            select(Producto)
            .where(Producto.id_categoria_producto == category.id)
            .order_by(Producto.orden, Producto.id)
            .options(
                selectinload(Producto.presentaciones)
                .joinedload(ProductoPresentacion.presentacion),
                selectinload(Producto.presentaciones).joinedload(
                    ProductoPresentacion.precios
                ),
            )
        )
        if solo_activos:
            product_stmt = product_stmt.where(Producto.activo.is_(True))
        if solo_disponibles:
            product_stmt = product_stmt.where(Producto.disponible.is_(True))
        products = list(self._session.execute(product_stmt).scalars())
        for product in products:
            product.presentaciones.sort(
                key=lambda association: (association.orden, association.id)
            )
        category._eager_products = products

    def get_catalogo_categorias_with_products(
        self,
        comercio_id: int,
        solo_activos: bool,
        solo_disponibles: bool,
    ) -> list[CategoriaProducto] | None:
        exists = self._session.execute(
            select(CategoriaProducto.id).where(
                CategoriaProducto.id_comercio == comercio_id
            )
        ).first()
        if not exists:
            return None
        categories = self.list_catalogo(comercio_id, solo_activos, solo_disponibles)
        return categories

    def get_catalogo_comercio(self, comercio_id: int) -> CategoriaProducto | None:
        return self._session.get(CategoriaProducto, comercio_id)

    def search_products_by_comercio(
        self,
        comercio_id: int,
        texto: str,
    ) -> list[Producto]:
        stmt = (
            select(Producto)
            .join(CategoriaProducto, Producto.id_categoria_producto == CategoriaProducto.id)
            .where(CategoriaProducto.id_comercio == comercio_id)
            .where(
                or_(
                    func.lower(Producto.nombre).contains(texto.lower()),
                    func.lower(func.coalesce(Producto.descripcion, "")).contains(
                        texto.lower()
                    ),
                )
            )
            .options(
                joinedload(Producto.categoria),
                selectinload(Producto.presentaciones).joinedload(
                    ProductoPresentacion.presentacion
                ),
            )
            .order_by(
                CategoriaProducto.orden,
                Producto.orden,
                Producto.id,
            )
        )
        products = list(self._session.execute(stmt).scalars())
        for product in products:
            product.presentaciones.sort(
                key=lambda association: (association.orden, association.id)
            )
        return products

    def find_by_exact_name_in_comercio(
        self,
        comercio_id: int,
        nombre: str,
    ) -> list[Producto]:
        stmt = (
            select(Producto)
            .join(CategoriaProducto, Producto.id_categoria_producto == CategoriaProducto.id)
            .where(
                CategoriaProducto.id_comercio == comercio_id,
                func.lower(Producto.nombre) == nombre.lower(),
            )
            .options(
                joinedload(Producto.categoria),
                selectinload(Producto.presentaciones)
                .joinedload(ProductoPresentacion.presentacion),
                selectinload(Producto.presentaciones).joinedload(
                    ProductoPresentacion.precios
                ),
            )
            .order_by(CategoriaProducto.orden, Producto.id)
        )
        products = list(self._session.execute(stmt).scalars())
        for product in products:
            product.presentaciones.sort(
                key=lambda association: (association.orden, association.id)
            )
        return products

    def list_disponibles(self, comercio_id: int) -> list[Producto] | None:
        exists = self._session.execute(
            select(CategoriaProducto.id).where(
                CategoriaProducto.id_comercio == comercio_id
            )
        ).first()
        if not exists:
            return None
        stmt = (
            select(Producto)
            .join(CategoriaProducto, Producto.id_categoria_producto == CategoriaProducto.id)
            .where(
                CategoriaProducto.id_comercio == comercio_id,
                CategoriaProducto.activo.is_(True),
                Producto.activo.is_(True),
                Producto.disponible.is_(True),
            )
            .order_by(
                CategoriaProducto.orden,
                Producto.orden,
                Producto.id,
            )
        )
        return list(self._session.execute(stmt).scalars())

    def list_recognizer_catalog(self, comercio_id: int) -> list[ProductoPresentacion] | None:
        exists = self._session.execute(
            select(CategoriaProducto.id).where(
                CategoriaProducto.id_comercio == comercio_id
            )
        ).first()
        if not exists:
            return None
        stmt = (
            select(ProductoPresentacion)
            .join(Producto, ProductoPresentacion.id_producto == Producto.id)
            .join(CategoriaProducto, Producto.id_categoria_producto == CategoriaProducto.id)
            .join(Presentacion, ProductoPresentacion.id_presentacion == Presentacion.id)
            .where(
                CategoriaProducto.id_comercio == comercio_id,
                CategoriaProducto.activo.is_(True),
                Producto.activo.is_(True),
                ProductoPresentacion.activo.is_(True),
                Presentacion.activo.is_(True),
            )
            .options(
                joinedload(ProductoPresentacion.producto).joinedload(Producto.categoria),
                joinedload(ProductoPresentacion.presentacion),
            )
            .order_by(
                CategoriaProducto.orden,
                Producto.orden,
                ProductoPresentacion.orden,
                ProductoPresentacion.id,
            )
        )
        return list(self._session.execute(stmt).scalars())

    def list_vendibles(self, comercio_id: int) -> list[Producto] | None:
        exists = self._session.execute(
            select(CategoriaProducto.id).where(
                CategoriaProducto.id_comercio == comercio_id
            )
        ).first()
        if not exists:
            return None
        stmt = (
            select(Producto)
            .join(
                ProductoPresentacion,
                Producto.id == ProductoPresentacion.id_producto,
            )
            .join(Precio, ProductoPresentacion.id == Precio.id_producto_presentacion)
            .join(
                CategoriaProducto,
                Producto.id_categoria_producto == CategoriaProducto.id,
            )
            .join(
                Presentacion,
                ProductoPresentacion.id_presentacion == Presentacion.id,
            )
            .where(
                CategoriaProducto.id_comercio == comercio_id,
                CategoriaProducto.activo.is_(True),
                Producto.activo.is_(True),
                Producto.disponible.is_(True),
                ProductoPresentacion.activo.is_(True),
                Presentacion.activo.is_(True),
            )
            .options(
                joinedload(Producto.categoria),
                selectinload(Producto.presentaciones)
                .joinedload(ProductoPresentacion.presentacion),
                selectinload(Producto.presentaciones).joinedload(
                    ProductoPresentacion.precios
                ),
            )
            .order_by(
                CategoriaProducto.orden,
                Producto.orden,
                ProductoPresentacion.orden,
                ProductoPresentacion.id,
            )
        )
        products = list(self._session.execute(stmt).unique().scalars())
        for product in products:
            keep = [
                association
                for association in product.presentaciones
                if (
                    association.activo
                    and association.presentacion.activo
                    and Decimal(str(association.precios[0].precio)) >= 0
                )
            ]
            keep.sort(key=lambda association: (association.orden, association.id))
            product.presentaciones = keep
        return products

    def list_incompletos(self, comercio_id: int) -> list[dict[str, object]] | None:
        products = self._session.execute(
            select(Producto)
            .join(CategoriaProducto, Producto.id_categoria_producto == CategoriaProducto.id)
            .where(CategoriaProducto.id_comercio == comercio_id)
            .order_by(CategoriaProducto.orden, Producto.id)
        ).scalars()
        incomplete: list[dict[str, object]] = []
        for product in products:
            problems: list[str] = []
            if not product.activo or not product.disponible:
                problems.append("producto_no_vendible")
            problems.extend(self._category_problems(product))
            problems.extend(self._presentation_problems(product))
            if problems:
                incomplete.append(
                    {
                        "id_producto": product.id,
                        "nombre": product.nombre,
                        "id_categoria_producto": product.id_categoria_producto,
                        "problemas": problems,
                    }
                )
        return incomplete

    def _category_problems(self, product: Producto) -> list[str]:
        if product.categoria.activo:
            return []
        return ["categoria_inactiva"]

    def _presentation_problems(self, product: Producto) -> list[str]:
        if not product.presentaciones:
            return ["sin_presentaciones"]
        problems: list[str] = []
        if not any(association.activo for association in product.presentaciones):
            problems.append("sin_presentaciones_activas")
        if not any(association.precios for association in product.presentaciones if association.activo):
            problems.append("presentaciones_activas_sin_precio")
        if (product.activo and product.disponible) and not problems:
            sellable = any(
                association.activo
                and association.presentacion.activo
                and association.precios
                for association in product.presentaciones
            )
            if not sellable:
                problems.append("disponible_sin_presentacion_vendible")
        return problems

    def get_detalle_categoria(
        self,
        categoria_producto_id: int,
    ) -> CategoriaProducto | None:
        stmt = (
            select(CategoriaProducto)
            .where(CategoriaProducto.id == categoria_producto_id)
            .options(
                selectinload(CategoriaProducto.productos)
                .joinedload(Producto.categoria),
                selectinload(CategoriaProducto.productos)
                .joinedload(Producto.presentaciones)
                .joinedload(ProductoPresentacion.presentacion),
                selectinload(CategoriaProducto.productos)
                .joinedload(Producto.presentaciones)
                .joinedload(ProductoPresentacion.precios),
            )
        )
        category = self._session.execute(stmt).scalar_one_or_none()
        if category is None:
            return None
        for product in category.productos:
            product.presentaciones.sort(
                key=lambda association: (association.orden, association.id)
            )
        return category
