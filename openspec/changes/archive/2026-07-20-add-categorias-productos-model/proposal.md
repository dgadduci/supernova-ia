## Why

Phase 1 / Subphase 1.5 introduces **CategoriasProductos** — the per-commerce product-category configuration table. Every `Comercio` will eventually curate its own product categories (descriptions, ordering, activation state) inline with the same shape used by other per-commerce child tables. This subphase lays down the table.

This change also resolves a long-standing naming inconsistency surfaced by earlier subphases: the `Comercio` model landed in Subphase 1.2 with `__tablename__ = "comercio"` (singular). The user's FK targets for new per-commerce child tables have consistently pointed at `"comercios.id"` (plural). The user has now confirmed the rename from `comercio` → `comercios` is the correct direction; the rename lands here.

## What Changes

- **BREAKING**: Rename the `Comercio` table from `comercio` to `comercios`. The SQLAlchemy class name remains `Comercio`. The class name is the public identifier (re-exported from `backend/models/__init__.py`); only the underlying DB table name changes. Any code or Alembic revision written against the old `comercio` table name must be updated in lock-step — currently the only forward consumer is this change, so no third-party impact.
- Add a new SQLAlchemy model `CategoriasProductos` in `backend/models/categorias_productos.py` with the columns the user supplied: `id` (autoincrement PK), `id_comercio` (Integer ForeignKey → `comercios.id`, `ondelete="CASCADE"`, indexed), `descripcion` (String ≤ 100, non-null), `activo` (Boolean, non-null, default `True`, server-default `"true"`), `orden` (Integer, non-null, default `0`, server-default `"0"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, the latter additionally `onupdate=func.now()`).
- `__tablename__ = "categorias_productos"`.
- Re-export `CategoriasProductos` from `backend/models/__init__.py`.
- **Explicitly out of scope** for this change: any relationship on `Comercio` (deferred to a dedicated wiring subphase); seed data; Alembic migrations; any service or API surface. Earlier per-commerce attempts (a brief, mis-scoped `ComercioMediosPago` build) were reverted before this change landed; only files for `CategoriasProductos` are new.

## Capabilities

### New Capabilities

- `categorias-productos`: Defines the `CategoriasProductos` SQLAlchemy model — the per-commerce product-category configuration table. Each row records a local description, activation flag, display order and lifecycle timestamps under one parent `Comercio` (cascade-deleted).

### Modified Capabilities

- `comercio`: No change to requirements; only the DB-level table identifier switches from `comercio` to `comercios`. Scenario assertions reference columns and FK targets (`comercio.id` had been string-form; Subphase 1.2 design D3 already accepted string-form FK targets, so the table-name change is silent for SQLAlchemy loaders that resolve tables by class).

## Impact

- **Modified code**: `backend/models/comercio.py` — `__tablename__` flips from `"comercio"` to `"comercios"`. Class name, columns, FK to `estado_comercio.id`, indexes, defaults, and timestamps are unchanged. The revert of an earlier mis-scoped attempt also removed the trade tests for it; this subphase does not re-introduce them.
- **New code**: `backend/models/categorias_productos.py`.
- **Re-export**: `backend/models/__init__.py` adds the `CategoriasProductos` import to its `__all__`.
- **Cross-model dependency** (table level): `categorias_productos.id_comercio` ForeignKey → `comercios.id` with `ON DELETE CASCADE`.
- **Archived change directories**: `2026-07-20-add-comercio-model/` is **left untouched** as the historical planning snapshot. The snapshot's `design.md` still records the singular `comercio` decision; that historical artifact is not retroactively rewritten.
- **No API, service, repository, or migration** introduced here.
