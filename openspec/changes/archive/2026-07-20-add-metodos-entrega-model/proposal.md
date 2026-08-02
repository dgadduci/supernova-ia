## Why

Phase 1 / Subphase 1.4 introduces **MetodosEntrega**, the reference catalog of delivery methods a commerce can offer its customers (e.g., `RETIRO_EN_LOCAL`, `DELIVERY_PROPIO`, `ENVIOS_CORREO`). Order intake and routing eventually need a stable, named catalog of options just like `MediosPago` does for payments; adding the table now keeps the model layer continuous and gives a future join-table subphase (e.g., `ComercioMetodoEntrega`) a target to reference.

Note: in Subphase 1.2 we deferred the `metodos_entrega` relationship on `Comercio` because `ComercioMetodoEntrega` did not exist. With this subphase we still defer that join table — `MetodosEntrega` here is the catalog, not the join.

## What Changes

- Add a new SQLAlchemy model `MetodosEntrega` in `backend/models/metodos_entrega.py` with the columns the user specified: `id` (autoincrement PK), `codigo` (String ≤ 50, unique, indexed), `descripcion` (String ≤ 100, non-null), `orden` (Integer, non-null), `activo` (Boolean, non-null, default `True`, server-default `"true"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, the latter additionally `onupdate=func.now()`).
- Add a table-level `CheckConstraint` named `orden_no_negativo` enforcing `orden >= 0`.
- `__tablename__ = "metodos_entrega"` as supplied.
- Re-export `MetodosEntrega` from `backend/models/__init__.py`.
- **Explicitly out of scope** for this change: the `ComercioMetodoEntrega` join table; the `Comercio.metodos_entrega` relationship (still deferred); any FK to `comercio` or to other tables; seed data; Alembic migrations; any service or API surface.

## Capabilities

### New Capabilities

- `metodos-entrega`: Defines the `MetodosEntrega` SQLAlchemy model — the reference catalog of delivery methods a commerce may offer. Holds a unique `codigo`, a human-readable `descripcion`, a non-negative `orden` (sorting), an `activo` flag for soft-disable, lifecycle timestamps, and a DB-level `CheckConstraint` preventing negative ordering values. Consumers (a future commerce-to-method association) will land in a separate subphase.

### Modified Capabilities

_None._ No existing spec requirements change with this proposal.

## Impact

- **New code** under `backend/models/metodos_entrega.py`, including a `__table_args__` tuple holding the `CheckConstraint`.
- **Re-export** from `backend/models/__init__.py` so consumers can `from backend.models import MetodosEntrega`.
- **No cross-model dependencies**: this model introduces no ForeignKeys to `comercio`, `estado_comercio`, or any other table. It stands alone in `Base.metadata`.
- **No API, service, repository, or migration** introduced here — those land in later subphases.
- **No `Comercio` change**: the deferred `metodos_entrega` relationship on `Comercio` stays deferred until `ComercioMetodoEntrega` exists. This subphase does not retroactively add the relationship.
- **Seed data** (rows like `RETIRO_EN_LOCAL`, `DELIVERY_PROPIO`, etc.) is deliberately deferred.
