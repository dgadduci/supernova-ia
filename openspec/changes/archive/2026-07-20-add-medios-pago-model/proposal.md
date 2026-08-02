## Why

Phase 1 / Subphase 1.3 introduces **MediosPago**, the reference table that catalogues the payment methods a commerce can offer its customers (e.g., `EFECTIVO`, `TRANSFERENCIA`, `MERCADO_PAGO`). Order intake eventually needs to attach an accepted payment to a customer order, and that requires a stable, named catalog of options rather than ad-hoc strings. Adding the table now keeps the model layer continuous and lets a future subphase wire `Comercio` (or any order entity) to this catalog without remodelling.

## What Changes

- Add a new SQLAlchemy model `MediosPago` in `backend/models/medios_pago.py` with the columns the user specified: `id` (autoincrement PK), `codigo` (String ≤ 50, unique, indexed), `descripcion` (String ≤ 100, non-null), `activo` (Boolean, default `True`, server-default `"true"`), and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime with `server_default=func.now()`, `fecha_ultima_modificacion` also `onupdate=func.now()`).
- `__tablename__ = "medios_pago"` as supplied.
- Re-export `MediosPago` from `backend/models/__init__.py`.
- **Explicitly out of scope** for this change: any FK association to `Comercio` or any future order entity; seed data; Alembic migrations; any service or API surface.

## Capabilities

### New Capabilities

- `medios-pago`: Defines the `MediosPago` SQLAlchemy model — the reference catalog of payment methods a commerce may offer. Holds a unique `codigo`, a human-readable `descripcion`, an `activo` flag for soft-disable, and lifecycle timestamps. Consumers (e.g., a commerce–payment association) will land in later subphases.

### Modified Capabilities

_None._ No existing spec requirements change with this proposal.

## Impact

- **New code** under `backend/models/medios_pago.py`.
- **Re-export** from `backend/models/__init__.py` so consumers can `from backend.models import MediosPago`.
- **No cross-model dependencies**: this model introduces no ForeignKeys to `estado_comercio`, `comercio`, or any other table. It stands alone in `Base.metadata`.
- **No API, service, repository, or migration** introduced here — those land in later subphases.
- **Seed data** (rows like `EFECTIVO`, `TRANSFERENCIA`, `MERCADO_PAGO`) and the relationship that ties `Comercio` to its accepted payment methods are deliberately deferred.
