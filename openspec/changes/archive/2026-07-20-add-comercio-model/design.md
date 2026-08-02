## Context

Subphase 1.1 introduced the reference table `estado_comercio` and the shared declarative `Base` in `backend/models/`. **Subphase 1.2** introduces the central entity of the multi-commerce ordering system: **Comercio**. Each customer order resolves to one `Comercio`; the model also stores the business profile, the address, locale preferences, lifecycle timestamps, and a foreign-key reference to `EstadoComercio`.

The user supplied the model body directly. Two deviations from the user's original paste were negotiated before this design:

1. **`estado` is a relationship, not a Python enum.** The original paste referenced `EstadoComercio.PRUEBA` and used `SqlEnum(EstadoComercio, …)`, which only works if `EstadoComercio` were a Python `enum.Enum`. Since 1.1 has already shipped `EstadoComercio` as a SQLAlchemy table, we replace the column with a foreign-key `estado_id` referencing `estado_comercio.id`, plus a relationship `estado`.
2. **`metodos_entrega` relationship is deferred.** The user's original body included `metodos_entrega: relationship("ComercioMetodoEntrega", …)`, but `ComercioMetodoEntrega` does not exist yet. The relationship is intentionally omitted; it will land with its own subphase.

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives in purpose-specific subdirectories under `backend/`.
- Implement only what is explicitly requested.
- Dev DB `supernova` and test DB `supernova_test`; both will eventually contain the new `comercio` table once a future subphase generates the migration.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy `Comercio` model whose column set exactly matches the user-supplied body (after the two negotiated deviations).
- Re-export `Comercio` from `backend/models/__init__.py` so consumers can import it from a stable path.
- Index `cuit`, mark `whatsapp` and `slug` unique + indexed for lookup performance.
- Keep the surface area minimal: no `__repr__`, no validators, no back-reference on `EstadoComercio`, no business logic.

**Non-Goals:**

- Alembic migrations (a separate subphase).
- Seeding `estado_comercio` reference rows (a separate subphase).
- The `metodos_entrega` relationship to `ComercioMetodoEntrega` (its own subphase).
- The `ComercioMetodoEntrega` model.
- A back-reference (`comercios`) on `EstadoComercio`.
- Any service, repository, API endpoint, or DTO layer.

## Decisions

**D1 — File: `backend/models/comercio.py` and re-export from `backend/models/__init__.py`.**
Per the convention established in Subphase 1.1: one purpose per file under `backend/models/`, `__init__.py` re-exports so consumers import from `backend.models`.

**D2 — ORM style: SQLAlchemy 2.0 typed declarations (`Mapped[…]` + `mapped_column(…)`).**
The user supplied the body in this style. Both SQLAlchemy 2.0 styles (`Column(…)` from 1.1 and `Mapped[…]` here) coexist without issue on the same `Base`; we follow the user's style for this model to keep the spec alignment faithful.

**D3 — `estado` as `estado_id` ForeignKey plus `estado` relationship.**
Replaces the user's original `SqlEnum` column with a non-null integer FK to `estado_comercio.id`. The relationship attribute is also named `estado`. Splitting the FK column and the relationship with different names (`estado_id` for the column, `estado` for the relationship) follows the SQLAlchemy 2.0 idiomatic pattern and avoids name collisions.

**D4 — Preserve all user-supplied `default=` and `server_default=` pairs.**
The user provided Python-side defaults (`default=`) and database-side defaults (`server_default=`) for `zona_horaria`, `moneda`, `idioma`. We keep both because they serve different layers (in-process inserts vs. raw SQL/DB-level). For the lifecycle timestamps, we keep `server_default=func.now()` and `onupdate=func.now()` as supplied; we do not add Python-side `default=` for those (the database owns them).

**D5 — Keep nullable/explicit-nullable columns exactly as supplied.**
`piso_departamento`, `codigo_postal`, `fecha_baja` are nullable. Everything else is non-null. No deviation from the user's body.

**D6 — Index/unique constraints exactly as supplied.**
- `cuit`: `index=True` (lookup by tax id).
- `whatsapp`: `unique=True, index=True` (one WhatsApp number per commerce; queried on every inbound message).
- `slug`: `unique=True, index=True` (used in public URLs).

These three are the only indexed columns in this change. We do not index address or locale columns; those can be revisited once the project's query patterns are observed.

**D7 — No `__repr__`, no validators, no relationships beyond `estado`.**
Per "Implement only what is explicitly requested" and "Avoid overengineering". Adding `__repr__` is a debug convenience, not requested; adding validators duplicates business logic that should live in a service layer (future subphase); adding a back-reference on `EstadoComercio` is a cross-file change outside this scope.

## Risks / Trade-offs

- **[Risk] `estado_id` is `nullable=False`, but `estado_comercio` is currently empty.** → Mitigation: not a problem today (no inserts happen before migrations/seeding land). A future subphase must seed the reference rows **before** any `Comercio` insert. The transition is sequenced so this never fails in production.
- **[Risk] Future subphases may need additional indexes (e.g., on `razon_social` or address fields).** → Mitigation: indexes are easy to add when actual query patterns are known. We add only the three the user supplied.
- **[Trade-off] Mixing SQLAlchemy declarative styles** (`Column(…)` in 1.1, `Mapped[…]` in 1.2). → Acceptable: both compile to the same `Table` metadata; no runtime impact, no migration impact. Future subphases can pick either style.
- **[Trade-off] `estado` relationship defaults to lazy load.** → Acceptable: the lookup table is small and rarely joined; an explicit `joinedload`/`selectinload` is easy to add at query time.

## Migration Plan

Not applicable. No migration is generated, applied, or rolled back in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test`.

## Open Questions

- None for this subphase. The next subphase will need to (a) generate the Alembic migration for both `comercio` and the prior `estado_comercio` table, and (b) seed `estado_comercio` so that `Comercio` inserts can satisfy the FK.
