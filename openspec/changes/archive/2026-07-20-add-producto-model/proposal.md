## Why

Phase 1 / Subphase 1.7 introduces **Producto**, the per-category-product row that anchors the catalog. Each `Producto` belongs to exactly one `CategoriaProducto` and is sold in zero or more `Presentacion` configurations through a join row in a new `ProductoPresentacion` table. This subphase finalizes the catalog + presentation relationships so that later subphases (order intake, search, listing) can navigate the catalog without ad-hoc joins.

This is also the first subphase in Phase 1 that touches three models at once, because the user's spec for `Producto` references two classes (`CategoriaProducto`, `ProductoPresentacion`) that didn't yet exist in the consistent form required. Two enabling changes land here in lock-step:

1. The `CategoriaProducto` class (currently `CategoriasProductos` from Subphase 1.5) is renamed to singular to match the user's forward-ref, and gains the `productos` relationship so `Producto.categoria` can use `back_populates="productos"`.
2. A minimal stub of `ProductoPresentacion` is added — just FKs and the lifecycle timestamps/flags needed for the relationship on `Producto` to resolve. The full schema (constraints, ordering, etc.) will land in a dedicated subphase once requirements are spelled out.

## What Changes

- **Refactor (Subphase 1.5 follow-up)**: rename the existing model class from `CategoriasProductos` to `CategoriaProducto` (file location `backend/models/categorias_productos.py` stays). Update the `__init__.py` re-export.
- **Back-reference added**: `CategoriaProducto.productos = relationship("Producto", back_populates="categoria")` so the `Producto.categoria` relationship can use `back_populates`.
- **Add a new SQLAlchemy model `Producto`** in `backend/models/producto.py` with `__tablename__ = "productos"`. Columns the user supplied: `id` (PK autoincrement), `id_categoria_producto` (Integer ForeignKey → `categorias_productos.id`, `ondelete="RESTRICT"`, indexed), `nombre` (String ≤ 150, non-null), `descripcion` (Text, nullable), `activo` (Boolean, default `True`, server-default `"true"`), `disponible` (Boolean, default `True`, server-default `"true"`), `orden` (Integer, default `0`, server-default `"0"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, the latter additionally `onupdate=func.now()`).
- Declare `__table_args__`: `UniqueConstraint("id_categoria_producto", "nombre", name="categoria_producto_nombre_unico")` and `CheckConstraint("orden >= 0", name="orden_no_negativo")`.
- Two relationships on `Producto`: `categoria = relationship("CategoriaProducto", back_populates="productos")` and `presentaciones = relationship("ProductoPresentacion", back_populates="producto")`.
- **Add a new stub model `ProductoPresentacion`** in `backend/models/producto_presentacion.py` with `__tablename__ = "producto_presentacion"`. Columns: `id` (PK), `id_producto` (Integer FK → `productos.id`, `ondelete="CASCADE"`, indexed, non-null), `id_presentacion` (Integer FK → `presentaciones.id`, `ondelete="CASCADE"`, indexed, non-null), `activo` (Boolean, default `True`, server-default `"true"`), `orden` (Integer, default `0`, server-default `"0"`), and lifecycle timestamps. A back-reference `producto = relationship("Producto", back_populates="presentaciones")` and a forward-ref `presentacion = relationship("Presentacion")` are declared (the `Presentacion` back-ref to `ProductoPresentacion` lands in its own subphase).
- Re-export `Producto`, `ProductoPresentacion`, and the renamed `CategoriaProducto` from `backend/models/__init__.py`.
- **Explicitly out of scope** for this change: full schema for `ProductoPresentacion` (constraints, ordering rules, uniqueness variants) — a dedicated subphase. Seed data; Alembic migrations; any service or API surface. The `Presentacion` model's `back_populates` for `ProductoPresentacion` (a related change). Migration of the renamed `CategoriasProductos` capability's main spec (handled at archive time as a delta).

## Capabilities

### New Capabilities

- `producto`: Defines the `Producto` SQLAlchemy model — the per-category product row carrying `nombre`, an optional `descripcion` (`Text`, nullable), separate `activo` (catalog-active) and `disponible` (in-stock) flags, an `orden` constrained `>= 0`, lifecycle timestamps, a foreign key to `categorias_productos.id` with `ON DELETE RESTRICT`, a unique `(id_categoria_producto, nombre)` per-category constraint, and relationships to `CategoriaProducto` (many-to-one) and `ProductoPresentacion` (one-to-many).
- `producto-presentacion`: Defines the `ProductoPresentacion` stub SQLAlchemy model — a join row between `productos` and `presentaciones`. Holds only the FKs, the `activo` flag, the `orden` integer, and lifecycle timestamps. Refinement lands in a dedicated follow-up subphase.

### Modified Capabilities

- `categorias-productos`: The class name `CategoriasProductos` renames to `CategoriaProducto` to match the user's forward-ref. A `productos` relationship is added so `Producto.categoria` resolves. Tablename `categorias_productos` (plural) stays.

## Impact

- **Modified files**: `backend/models/categorias_productos.py` (class rename + new relationship), `backend/models/__init__.py` (re-exports adjusted).
- **New code** under `backend/models/producto.py` and `backend/models/producto_presentacion.py`.
- **Class name change is observable** in any consumer code that imports `CategoriasProductos` directly. The re-export slot for `CategoriaProducto` replaces the previous slot for `CategoriasProductos`.
- **`__tablename__` for `categorias_productos` is unchanged** — no DB-level rename required by this change.
- **First `ondelete="RESTRICT"`** in the model layer. Choosing `RESTRICT` on `productos.id_categoria_producto` means a `CategoriaProducto` row cannot be deleted while any `Producto` still references it. Aligns with the catalog-immutability assumption that `categoria_producto` is a logical reference table.
- **First `Text` column** in the model layer (`Producto.descripcion`).
- **First new-flag** concept (`disponible`): separate from `activo`. The two flags answer different questions — `activo` marks catalog availability (admin-controlled), `disponible` marks the live stock state (operationally toggled).
- **Cross-model dependencies** (table level): `productos.id_categoria_producto` → `categorias_productos.id` (`RESTRICT`); `producto_presentacion.id_producto` → `productos.id` (`CASCADE`); `producto_presentacion.id_presentacion` → `presentaciones.id` (`CASCADE`).
- **No API, service, repository, or migration** introduced here.
