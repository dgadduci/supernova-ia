from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.dependencies import get_session, require_admin_token
from backend.schemas.categoria_producto import CategoriaProductoResponse
from backend.schemas.categoria_producto import CategoriaProductoDetalleResponse
from backend.schemas.precio import PrecioResponse
from backend.schemas.producto_query import (
    ProductoCategoriaResumenResponse,
    ProductoComercioCatalogoResponse,
    ProductoDetalleResponse,
    ProductoIncompletoResponse,
    ProductoPrecioResumenResponse,
    ProductoPresentacionDetalleResponse,
)
from backend.services.exceptions import (
    CategoriaProductoNotFound,
    ComercioNotFound,
    InvalidProducto,
    PresentacionNotFound,
    ProductoNotFound,
)
from backend.services.producto_query_service import ProductoQueryService

router = APIRouter(
    tags=["productos-consultas"],
    dependencies=[Depends(require_admin_token)],
)


def _service(session: Session = Depends(get_session)) -> ProductoQueryService:
    return ProductoQueryService(session)


def _producto_presentacion_detalle(association) -> ProductoPresentacionDetalleResponse:
    return ProductoPresentacionDetalleResponse(
        id=association.id,
        id_producto=association.id_producto,
        id_presentacion=association.id_presentacion,
        activo=association.activo,
        orden=association.orden,
        fecha_alta=association.fecha_alta,
        fecha_ultima_modificacion=association.fecha_ultima_modificacion,
        presentacion=association.presentacion,
        precios=[PrecioResponse.model_validate(precio) for precio in association.precios],
    )


def _producto_detalle(producto) -> ProductoDetalleResponse:
    comercio_id = producto.categoria.id_comercio if producto.categoria is not None else 0
    return ProductoDetalleResponse(
        id=producto.id,
        id_categoria_producto=producto.id_categoria_producto,
        nombre=producto.nombre,
        descripcion=producto.descripcion,
        activo=producto.activo,
        disponible=producto.disponible,
        orden=producto.orden,
        fecha_alta=producto.fecha_alta,
        fecha_ultima_modificacion=producto.fecha_ultima_modificacion,
        categoria=producto.categoria,
        id_comercio=comercio_id,
        presentaciones=[_producto_presentacion_detalle(association) for association in producto.presentaciones],
    )


@router.get(
    "/productos/{producto_id}/detalle",
    response_model=ProductoDetalleResponse,
)
def get_producto_detalle(
    producto_id: int,
    service: ProductoQueryService = Depends(_service),
) -> ProductoDetalleResponse:
    try:
        producto = service.get_detalle(producto_id)
    except ProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _producto_detalle(producto)


@router.get(
    "/comercios/{comercio_id}/catalogo",
    response_model=ProductoComercioCatalogoResponse,
)
def get_catalogo_comercio(
    comercio_id: int,
    solo_activos: bool = Query(default=True),
    solo_disponibles: bool = Query(default=True),
    service: ProductoQueryService = Depends(_service),
) -> ProductoComercioCatalogoResponse:
    try:
        comercio, categories = service.list_catalogo(comercio_id, solo_activos, solo_disponibles)
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    payload = ProductoComercioCatalogoResponse(
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
        estado_id=comercio.estado_id,
        zona_horaria=comercio.zona_horaria,
        moneda=comercio.moneda,
        idioma=comercio.idioma,
        fecha_alta=comercio.fecha_alta,
        fecha_ultima_modificacion=comercio.fecha_ultima_modificacion,
        fecha_baja=comercio.fecha_baja,
        categorias=[],
    )
    for category in categories:
        products = getattr(category, "_eager_products", list(category.productos))
        category_payload = ProductoCategoriaResumenResponse(
            id=category.id,
            id_comercio=category.id_comercio,
            descripcion=category.descripcion,
            activo=category.activo,
            orden=category.orden,
            fecha_alta=category.fecha_alta,
            fecha_ultima_modificacion=category.fecha_ultima_modificacion,
            productos=[],
        )
        for product in products:
            category_payload.productos.append(_producto_detalle(product))
        payload.categorias.append(category_payload)
    return payload


@router.get(
    "/productos/{producto_id}/presentaciones",
    response_model=list[ProductoPresentacionDetalleResponse],
)
def list_producto_presentaciones(
    producto_id: int,
    service: ProductoQueryService = Depends(_service),
) -> list[ProductoPresentacionDetalleResponse]:
    try:
        return [
            _producto_presentacion_detalle(association)
            for association in service.list_presentaciones(producto_id)
        ]
    except ProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/productos/{producto_id}/presentaciones/{presentacion_id}",
    response_model=ProductoPresentacionDetalleResponse,
)
def get_producto_presentacion(
    producto_id: int,
    presentacion_id: int,
    service: ProductoQueryService = Depends(_service),
) -> ProductoPresentacionDetalleResponse:
    try:
        association = service.get_asociacion(producto_id, presentacion_id)
    except (ProductoNotFound, PresentacionNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _producto_presentacion_detalle(association)


@router.get(
    "/productos/{producto_id}/presentaciones/{presentacion_id}/precio",
    response_model=ProductoPrecioResumenResponse,
)
def get_precio_producto_presentacion(
    producto_id: int,
    presentacion_id: int,
    service: ProductoQueryService = Depends(_service),
) -> ProductoPrecioResumenResponse:
    try:
        precio = service.get_precio_asociacion(producto_id, presentacion_id)
    except (ProductoNotFound, PresentacionNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ProductoPrecioResumenResponse(
        id_producto_presentacion=precio.id_producto_presentacion,
        id_presentacion=presentacion_id,
        id_producto=producto_id,
        presentacion_id=presentacion_id,
        presentacion_codigo=precio.producto_presentacion.presentacion.codigo,
        presentacion_descripcion=precio.producto_presentacion.presentacion.descripcion,
        precio=Decimal(str(precio.precio)),
        fecha_alta=precio.fecha_alta,
    )


@router.get(
    "/productos/{producto_id}/precios",
    response_model=list[ProductoPrecioResumenResponse],
)
def list_producto_precios(
    producto_id: int,
    service: ProductoQueryService = Depends(_service),
) -> list[ProductoPrecioResumenResponse]:
    try:
        precios = service.list_precios(producto_id)
    except ProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    resumen: list[ProductoPrecioResumenResponse] = []
    for precio in precios:
        association = precio.producto_presentacion
        resumen.append(
            ProductoPrecioResumenResponse(
                id_producto_presentacion=association.id,
                id_presentacion=association.id_presentacion,
                id_producto=association.id_producto,
                presentacion_id=association.id_presentacion,
                presentacion_codigo=association.presentacion.codigo,
                presentacion_descripcion=association.presentacion.descripcion,
                precio=Decimal(str(precio.precio)),
                fecha_alta=precio.fecha_alta,
            )
        )
    return resumen


@router.get(
    "/comercios/{comercio_id}/productos/buscar",
    response_model=list[ProductoDetalleResponse],
)
def search_productos(
    comercio_id: int,
    q: str = Query(),
    service: ProductoQueryService = Depends(_service),
) -> list[ProductoDetalleResponse]:
    if not q.strip():
        raise HTTPException(status_code=400, detail="texto must not be empty")
    try:
        products = service.search(comercio_id, q)
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidProducto as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return [_producto_detalle(product) for product in products]


@router.get(
    "/comercios/{comercio_id}/productos/por-nombre",
    response_model=list[ProductoDetalleResponse],
)
def find_productos_por_nombre(
    comercio_id: int,
    nombre: str = Query(min_length=1),
    service: ProductoQueryService = Depends(_service),
) -> list[ProductoDetalleResponse]:
    try:
        products = service.find_by_nombre(comercio_id, nombre)
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [_producto_detalle(product) for product in products]


@router.get(
    "/comercios/{comercio_id}/productos/disponibles",
    response_model=list[ProductoDetalleResponse],
)
def list_productos_disponibles(
    comercio_id: int,
    service: ProductoQueryService = Depends(_service),
) -> list[ProductoDetalleResponse]:
    try:
        products = service.list_disponibles(comercio_id)
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [_producto_detalle(product) for product in products]


@router.get(
    "/comercios/{comercio_id}/productos/vendibles",
    response_model=list[ProductoDetalleResponse],
)
def list_productos_vendibles(
    comercio_id: int,
    service: ProductoQueryService = Depends(_service),
) -> list[ProductoDetalleResponse]:
    try:
        products = service.list_vendibles(comercio_id)
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [_producto_detalle(product) for product in products]


@router.get(
    "/comercios/{comercio_id}/productos/incompletos",
    response_model=list[ProductoIncompletoResponse],
)
def list_productos_incompletos(
    comercio_id: int,
    service: ProductoQueryService = Depends(_service),
) -> list[ProductoIncompletoResponse]:
    try:
        rows = service.list_incompletos(comercio_id)
    except ComercioNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [ProductoIncompletoResponse(**row) for row in rows]


@router.get(
    "/categorias-productos/{categoria_producto_id}/productos-detalle",
    response_model=CategoriaProductoDetalleResponse,
)
def get_categoria_productos_detalle(
    categoria_producto_id: int,
    service: ProductoQueryService = Depends(_service),
) -> CategoriaProductoDetalleResponse:
    try:
        category = service.get_detalle_categoria(categoria_producto_id)
    except CategoriaProductoNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    payload = CategoriaProductoDetalleResponse(
        id=category.id,
        id_comercio=category.id_comercio,
        descripcion=category.descripcion,
        activo=category.activo,
        orden=category.orden,
        fecha_alta=category.fecha_alta,
        fecha_ultima_modificacion=category.fecha_ultima_modificacion,
    )
    for product in category.productos:
        payload.productos.append(_producto_detalle(product))
    return payload
