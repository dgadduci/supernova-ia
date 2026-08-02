## Why

Phase 1 / Subphase 1.2 introduces the central entity of the multi-commerce system: **Comercio**. Each customer order ultimately resolves to a single commerce; the system also needs the commerce's business profile (legal name, tax id, WhatsApp channel) and geographical/locale metadata to operate correctly. Without this model, neither the order-routing layer (Phase 2+) nor any subphase that references a commerce can be built.

## What Changes

- Add a new SQLAlchemy model `Comercio` in `backend/models/comercio.py` with the column set the user specified: `id` (autoincrement PK), `nombre_fantasia`, `nombre_corto`, `razon_social`, `cuit`, `whatsapp`, address columns (`calle`, `numero`, `piso_departamento`, `localidad`, `provincia`, `codigo_postal`), `slug`, `estado_id` (FK to `estado_comercio.id`) with a `relationship` to `EstadoComercio`, locale columns (`zona_horaria`, `moneda`, `idioma`) with sensible defaults, and lifecycle timestamps (`fecha_alta`, `fecha_ultima_modificacion`, `fecha_baja`).
- Indexes / unique constraints: `cuit` indexed; `whatsapp` unique + indexed; `slug` unique + indexed.
- Re-export `Comercio` from `backend/models/__init__.py`.
- **Explicitly out of scope** for this change: the `metodos_entrega` relationship to `ComercioMetodoEntrega` (deferred to its own subphase); the `ComercioMetodoEntrega` model itself; Alembic migrations; seeding the `estado_comercio` reference rows.

## Capabilities

### New Capabilities

- `comercio`: Defines the `Comercio` SQLAlchemy model — the central reference entity for a commerce. Persists its identity, business profile, address, locale preferences, lifecycle timestamps, and a foreign-key reference to the `EstadoComercio` lookup table created in Subphase 1.1.

### Modified Capabilities

_None._ The `estado-comercio` capability introduced in Subphase 1.1 is referenced via FK, but its requirements are unchanged.

## Impact

- **New code** under `backend/models/comercio.py`.
- **Cross-model dependency**: `Comercio.estado_id` is a `ForeignKey("estado_comercio.id")`. Both tables will live in the same `Base.metadata` once Alembic is configured in a later subphase.
- **No API, service, repository, or migration** introduced here — those land in later subphases.
- **No data row backfill**: the `estado_id` column is `nullable=False`, so any insert requires a row already present in `estado_comercio`. Seeding `estado_comercio` belongs to a dedicated subphase and is out of scope here.
