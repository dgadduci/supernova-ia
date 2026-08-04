
from sqlalchemy.orm import Session

from backend.models import (
    CategoriaProducto,
    Comercio,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.repositories.producto_query_repository import ProductoQueryRepository
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    InvalidProducto,
    PresentacionNotFound,
    ProductoNotFound,
)
from backend.services.producto_alias_service import ProductoAliasService


def _build_catalog_dict(pp: ProductoPresentacion) -> dict[str, object]:
    return {
        "producto_presentacion_id": pp.id,
        "producto_id": pp.id_producto,
        "presentacion_id": pp.id_presentacion,
        "categoria_id": pp.producto.id_categoria_producto,
        "producto_nombre": pp.producto.nombre,
        "categoria_nombre": pp.producto.categoria.descripcion,
        "presentacion_codigo": pp.presentacion.codigo,
        "presentacion_descripcion": pp.presentacion.descripcion,
        "producto_activo": bool(pp.producto.activo),
        "presentacion_activo": bool(pp.presentacion.activo),
        "activo": bool(pp.activo),
        "disponible": bool(pp.producto.disponible),
    }


class ProductoQueryService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ProductoQueryRepository(session)
        self._alias_service = ProductoAliasService(session)

    def get_detalle(self, producto_id: int) -> Producto:
        producto = self._repo.get_detalle(producto_id)
        if producto is None:
            raise ProductoNotFound(producto_id)
        return producto

    def list_presentaciones_by_ids(
        self,
        producto_presentacion_ids: list[int],
    ) -> list[dict[str, object]]:
        presentations = self._repo.list_presentaciones_by_ids(producto_presentacion_ids)
        catalog = [_build_catalog_dict(pp) for pp in presentations]
        self._attach_aliases(catalog)
        return catalog

    def list_recognizer_catalog(self, comercio_id: int) -> list[dict[str, object]]:
        presentations = self._repo.list_recognizer_catalog(comercio_id) or []
        catalog = [_build_catalog_dict(pp) for pp in presentations]
        self._attach_aliases(catalog)
        return catalog

    def _attach_aliases(self, catalog: list[dict[str, object]]) -> None:
        if not catalog:
            return
        projection = self._alias_service.project_recognition_data(catalog)
        for row in catalog:
            pid = row.get("producto_id")
            ppid = row.get("producto_presentacion_id")
            if pid is None or ppid is None:
                continue
            if not isinstance(pid, int) or not isinstance(ppid, int):
                continue
            aliases = projection.get((pid, ppid))
            if aliases is None:
                continue
            row["aliases"] = {
                "general_aliases": list(aliases.general_aliases),
                "specific_aliases": list(aliases.specific_aliases),
            }

    def list_presentaciones(self, producto_id: int) -> list[ProductoPresentacion]:
        asociaciones = self._repo.list_presentaciones(producto_id)
        if asociaciones is None:
            raise ProductoNotFound(producto_id)
        return asociaciones

    def get_asociacion(
        self,
        producto_id: int,
        presentacion_id: int,
    ) -> ProductoPresentacion:
        if self._session.get(Producto, producto_id) is None:
            raise ProductoNotFound(producto_id)
        if self._session.get(Presentacion, presentacion_id) is None:
            raise PresentacionNotFound(presentacion_id)
        association = self._repo.get_asociacion(producto_id, presentacion_id)
        if association is None:
            raise ProductoNotFound(producto_id)
        return association

    def get_precio_asociacion(
        self,
        producto_id: int,
        presentacion_id: int,
    ) -> Precio:
        association = self.get_asociacion(producto_id, presentacion_id)
        if not association.precios:
            raise ProductoNotFound(producto_id)
        return association.precios[0]

    def list_precios(self, producto_id: int) -> list[Precio]:
        precios = self._repo.list_precios(producto_id)
        if precios is None:
            raise ProductoNotFound(producto_id)
        return precios

    def list_catalogo(
        self,
        comercio_id: int,
        solo_activos: bool,
        solo_disponibles: bool,
    ) -> tuple[Comercio, list[CategoriaProducto]]:
        if self._session.get(Comercio, comercio_id) is None:
            raise ComercioNotFound(comercio_id)
        categories = self._repo.list_catalogo(comercio_id, solo_activos, solo_disponibles)
        if categories is None:
            return self._session.get(Comercio, comercio_id), []
        return self._session.get(Comercio, comercio_id), categories

    def search(
        self,
        comercio_id: int,
        texto: str,
    ) -> list[Producto]:
        if self._session.get(Comercio, comercio_id) is None:
            raise ComercioNotFound(comercio_id)
        cleaned = texto.strip()
        if not cleaned:
            raise InvalidProducto("texto must not be empty")
        return self._repo.search_products_by_comercio(comercio_id, cleaned)

    def find_by_nombre(
        self,
        comercio_id: int,
        nombre: str,
    ) -> list[Producto]:
        if self._session.get(Comercio, comercio_id) is None:
            raise ComercioNotFound(comercio_id)
        cleaned = nombre.strip()
        if not cleaned:
            raise ProductoNotFound(comercio_id)
        products = self._repo.find_by_exact_name_in_comercio(comercio_id, cleaned)
        if not products:
            raise ProductoNotFound(comercio_id)
        return products

    def list_disponibles(self, comercio_id: int) -> list[Producto]:
        if self._session.get(Comercio, comercio_id) is None:
            raise ComercioNotFound(comercio_id)
        products = self._repo.list_disponibles(comercio_id)
        if products is None:
            return []
        return products

    def list_vendibles(self, comercio_id: int) -> list[Producto]:
        if self._session.get(Comercio, comercio_id) is None:
            raise ComercioNotFound(comercio_id)
        products = self._repo.list_vendibles(comercio_id)
        if products is None:
            return []
        return products

    def list_incompletos(self, comercio_id: int) -> list[dict[str, object]]:
        if self._session.get(Comercio, comercio_id) is None:
            raise ComercioNotFound(comercio_id)
        result = self._repo.list_incompletos(comercio_id)
        return result or []

    def get_detalle_categoria(
        self,
        categoria_producto_id: int,
    ) -> CategoriaProducto:
        category = self._repo.get_detalle_categoria(categoria_producto_id)
        if category is None:
            raise CategoriaProductoNotFound(categoria_producto_id)
        return category
