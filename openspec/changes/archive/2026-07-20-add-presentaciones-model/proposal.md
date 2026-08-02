## Why

Phase 1 / Subphase 1.6 introduces **Presentacion**, the per-commerce product-presentation configuration. A comercio sells products, and each product can be offered in multiple *presentaciones* (size variants, packaging options, etc. — for example, "1kg", "2kg", "500g", "pack x3"). Each comercio defines its own presentations inline (with a per-comercio code and description), so the table mirrors the per-comercio child-table pattern now established in Phase 1 but adds two schema-level invariants: a `(id_comercio, codigo)` composite uniqueness and a `(id_comercio, descripcion)` composite uniqueness, plus the same non-negative `orden` check constraint introduced for `MetodosEntrega` in Subphase 1.4.

This subphase also lands the first `UniqueConstraint` (composite) in the model layer. The two new table-level uniqueness rules enforce that, within a single comercio, no two presentations share the same code or description — across comercios, those values may legitimately repeat. The `CheckConstraint` matches what `MetodosEntrega` already carries.

## What Changes

- Add a new SQLAlchemy model `Presentacion` in `backend/models/presentaciones.py` with `__tablename__ = "presentaciones"`.
- Declare `__table_args__` with three table-level constraints, exactly as supplied:
  - `UniqueConstraint("id_comercio", "codigo", name="comercio_presentacion_codigo_unico")`
  - `UniqueConstraint("id_comercio", "descripcion", name="comercio_presentacion_descripcion_unica")`
  - `CheckConstraint("orden >= 0", name="orden_no_negativo")`
- Add the columns the user supplied: `id` (autoincrement PK), `id_comercio` (Integer ForeignKey → `comercios.id`, `ondelete="CASCADE"`, indexed), `codigo` (String ≤ 50, non-null), `descripcion` (String ≤ 100, non-null), `activo` (Boolean, non-null, default `True`, server-default `"true"`), `orden` (Integer, non-null, default `0`, server-default `"0"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, the latter additionally `onupdate=func.now()`).
- Re-export `Presentacion` from `backend/models/__init__.py`.
- **Explicitly out of scope** for this change: any relationship from `Comercio` (deferred to a dedicated subphase); seed data; Alembic migrations; any service or API surface.

## Capabilities

### New Capabilities

- `presentaciones`: Defines the `Presentacion` SQLAlchemy model — the per-commerce product-presentation configuration. Each row records a per-comercio code and description (unique within that comercio), an activation flag, a non-negative display order, and lifecycle timestamps. Two composite unique constraints enforce that, within a comercio, no two rows share the same code or description. A non-negative `orden` is enforced via a `CheckConstraint`.

### Modified Capabilities

_None._ No existing spec requirements change with this proposal. `comercio` is referenced via FK (to the post-1.5 `comercios.id`), but its requirements are unchanged.

## Impact

- **New code** under `backend/models/presentaciones.py`.
- **Re-export** from `backend/models/__init__.py` so consumers can `from backend.models import Presentacion`.
- **Cross-model dependency** (table level): `presentaciones.id_comercio` ForeignKey → `comercios.id` with `ON DELETE CASCADE`.
- **First `UniqueConstraint` in the model layer.** PostgreSQL will create two unique B-tree indexes (one per composite unique constraint) automatically. The legacy `unique=True` index patterns of earlier subphases are not used here — uniqueness is enforced per-comercio via the composite constraints, not globally.
- **Second `CheckConstraint` in the model layer.** Mirrors `MetodosEntrega` (Subphase 1.4); same `name="orden_no_negativo"`. Note: constraint names are scoped per-table in PostgreSQL, so two tables can each carry a constraint with the same logical name without conflict.
- **No API, service, repository, or migration** introduced here.
