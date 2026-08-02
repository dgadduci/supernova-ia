## Why

Phase 1 / Subphase 1.8 introduces **Precio**, the price-per-product-presentation row. Each `ProductoPresentacion` represents a product offered in a particular presentation (e.g., "1kg of coffee"); pricing lives alongside, in its own row, with a 1:1 constraint per `ProductoPresentacion`. This unlocks price history, per-commerce overrides, and currency-aware math without polluting the join table.

The user's FK target (`"producto_presentaciones.id"`, plural) clashes with the current live table name (`producto_presentacion`, singular, set during Subphase 1.7). The user has confirmed the rename `producto_presentacion` → `producto_presentaciones` so the FK resolves literally, mirroring the `comercio` → `comercios` rename of Subphase 1.5.

Two enabling changes land here in lock-step:

1. The `ProductoPresentacion` table name switches to plural `producto_presentaciones` (Python-side only; the table is empty so no DB ALTER required).
2. A `precios` relationship back-reference lands on `ProductoPresentacion` so `Precio.producto_presentacion` resolves with `back_populates`.

## What Changes

- **Refactor (Subphase 1.7 follow-up)**: rename `ProductoPresentacion.__tablename__` from `"producto_presentacion"` to `"producto_presentaciones"`. Class name stays `ProductoPresentacion`. No data migration required (the table is empty).
- **Add a new SQLAlchemy model `Precio`** in `backend/models/precio.py` with `__tablename__ = "producto_precios"`. Columns the user supplied: `id` (PK autoincrement), `id_producto_presentacion` (Integer ForeignKey → `producto_presentaciones.id`, `ondelete="RESTRICT"`, indexed), `precio` (`Mapped[Decimal]` via `Numeric(12, 2)`, non-null), and `fecha_alta` (timezone-aware DateTime, non-null, `server_default=func.now()`).
- Declare `__table_args__`:
  - `CheckConstraint("precio >= 0", name="precio_no_negativo")`
  - `Index("id_producto_presentacion", unique=True)` — the unique index enforces 1:1 between a `ProductoPresentacion` row and its price.
- A `producto_presentacion = relationship("ProductoPresentacion", back_populates="precios")` attribute on `Precio`.
- A `precios = relationship("Precio", back_populates="producto_presentacion")` back-reference on `ProductoPresentacion`.
- Re-export `Precio` from `backend/models/__init__.py`.
- **Explicitly out of scope** for this change: `fecha_ultima_modificacion`, `activo` flags, currency columns, multi-currency support, soft-delete lifecycle, Alembic migrations, seed data, any service or API surface.

## Capabilities

### New Capabilities

- `precio`: Defines the `Precio` SQLAlchemy model — the per-product-presentation price row. Holds a `Numeric(12, 2)` price (non-negative, enforced by `precio_no_negativo` check constraint) plus the FK to `producto_presentaciones.id` (RESTRICT) and a unique index on `id_producto_presentacion` enforcing 1:1 between a product-presentation pair and its price. Carries the lifecycle `fecha_alta` timestamp.

### Modified Capabilities

- `producto-presentacion`: The existing `ProductoPresentacion model definition` requirement gains a new `precios` relationship scenario (one-to-many back-reference to `Precio`) and updates the table-name scenario from `producto_presentacion` to `producto_presentaciones`. Column set, FKs, defaults, constraints, and timestamps remain unchanged.

## Impact

- **Modified files**: `backend/models/producto_presentacion.py` (tablename rename + new `precios` relationship attribute), `backend/models/__init__.py` (re-export).
- **New code** under `backend/models/precio.py`.
- **`__tablename__` for `ProductoPresentacion`** flips from singular to plural — class name unchanged.
- **First `Numeric` / `Decimal` column** in the model layer. New imports: `Decimal` (from `decimal`) and `Numeric`, `Index` (from `sqlalchemy`).
- **First `Index("column", unique=True)`** — equivalent to declaring `unique=True` on a column, expressed as a `__table_args__` entry. We preserve the user's explicit form because it lives next to the check constraint in `__table_args__`, surfacing both invariants together.
- **First `server_default=func.now()` only (no `onupdate=`)** — `Precio` has no modification timestamp column, because there is no `fecha_ultima_modificacion`.
- **Back-reference plumbing**: `ProductoPresentacion.precios` mirrors `Producto.presentaciones`. Three deep cycle through `Precio.producto_presentacion`. All still use forward-ref strings.
- **No API, service, repository, or migration** introduced here.
