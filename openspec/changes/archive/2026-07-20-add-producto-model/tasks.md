## 1. Prerequisite: rename CategoriaProducto

- [x] 1.1 In `backend/models/categorias_productos.py`, rename `class CategoriasProductos(Base)` to `class CategoriaProducto(Base)`; add `productos: Mapped[list["Producto"]] = relationship(back_populates="categoria")` so `Producto.categoria` resolves

## 2. New models

- [x] 2.1 Create `backend/models/producto.py` containing `class Producto(Base)` with `__tablename__ = "productos"`, a `__table_args__` tuple declaring `UniqueConstraint("id_categoria_producto", "nombre", name="categoria_producto_nombre_unico")` and `CheckConstraint("orden >= 0", name="orden_no_negativo")`, and the columns: `id` (PK autoincrement), `id_categoria_producto` (Integer ForeignKey to `categorias_productos.id`, `ondelete="RESTRICT"`, indexed, non-null), `nombre` (String ≤ 150, non-null), `descripcion` (Text, nullable), `activo` (Boolean, non-null, default `True`, server_default `"true"`), `disponible` (Boolean, non-null, default `True`, server_default `"true"`), `orden` (Integer, non-null, default `0`, server_default `"0"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, the latter additionally `onupdate=func.now()`); relationships `categoria: Mapped["CategoriaProducto"] = relationship(back_populates="productos")` and `presentaciones: Mapped[list["ProductoPresentacion"]] = relationship(back_populates="producto")`
- [x] 2.2 Create `backend/models/producto_presentacion.py` containing `class ProductoPresentacion(Base)` (stub) with `__tablename__ = "producto_presentacion"` and the columns: `id` (PK autoincrement), `id_producto` (Integer ForeignKey to `productos.id`, `ondelete="CASCADE"`, indexed, non-null), `id_presentacion` (Integer ForeignKey to `presentaciones.id`, `ondelete="CASCADE"`, indexed, non-null), `activo` (Boolean, non-null, default `True`, server_default `"true"`), `orden` (Integer, non-null, default `0`, server_default `"0"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, the latter additionally `onupdate=func.now()`); relationships `producto: Mapped["Producto"] = relationship(back_populates="presentaciones")` and `presentacion: Mapped["Presentacion"] = relationship()`

## 3. Re-export

- [x] 3.1 Update `backend/models/__init__.py`: replace `CategoriasProductos` (import + `__all__`) with `CategoriaProducto`; add imports for `Producto` and `ProductoPresentacion` (and update `__all__`)

## 4. Verification

- [x] 4.1 Activate the project-local `venv` and run `python -c "from backend.models import Producto, ProductoPresentacion, CategoriaProducto"` to confirm all three imports load without error
- [x] 4.2 Inspect `Producto.__table__.columns` and confirm: `id` PK autoincrement; `id_categoria_producto` Integer ForeignKey to `categorias_productos.id` indexed non-null; `nombre` String ≤ 150 non-null; `descripcion` Text nullable; `activo` Boolean default True + server_default "true"; `disponible` Boolean default True + server_default "true"; `orden` Integer default 0 + server_default "0"; lifecycle timestamps tz-aware with supplied defaults
- [x] 4.3 Confirm `Producto.id_categoria_producto` ForeignKey targets `categorias_productos.id` and its `ondelete` is set to `RESTRICT`
- [x] 4.4 Confirm `Producto.__table__.constraints` carries: `UniqueConstraint` named `categoria_producto_nombre_unico` over `(id_categoria_producto, nombre)`; `CheckConstraint` named `orden_no_negativo` with SQL `orden >= 0`
- [x] 4.5 Confirm `Producto.categoria` and `Producto.presentaciones` relationships resolve: `categoria` → `CategoriaProducto`, `presentaciones` → list of `ProductoPresentacion`
- [x] 4.6 Confirm `Producto.__tablename__ == "productos"`
- [x] 4.7 Inspect `ProductoPresentacion.__table__.columns` and confirm: `id` PK; `id_producto` Indexed Integer FK to `productos.id` non-null; `id_presentacion` Indexed Integer FK to `presentaciones.id` non-null; `activo` Boolean default True + server_default "true"; `orden` Integer default 0 + server_default "0"; lifecycle timestamps tz-aware with supplied defaults
- [x] 4.8 Confirm `ProductoPresentacion.id_producto.foreign_keys[0].target_fullname == "productos.id"` with `ondelete == "CASCADE"`, and the same for `id_presentacion` → `presentaciones.id`
- [x] 4.9 Confirm `ProductoPresentacion.__tablename__ == "producto_presentacion"`
- [x] 4.10 Confirm `CategoriaProducto` exists with `__tablename__ == "categorias_productos"` (tablename unchanged) and `CategoriaProducto.productos` relationship resolves to a list of `Producto` instances
- [x] 4.11 Confirm `Base.metadata` registers all expected tables (`comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`, `presentaciones`, `productos`, `producto_presentacion`)
