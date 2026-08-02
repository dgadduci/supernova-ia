## Context

The SQLAlchemy model layer of supernova-ia is being built up in small, single-purpose subphases. Subphase 1.1 introduced the `estado_comercio` lookup table and the shared declarative `Base` (in `backend/models/base.py`); Subphase 1.2 added `Comercio` (with its `estado_id` foreign key to `estado_comercio`). **Subphase 1.3** continues the catalog of reference data with **MediosPago** — the table that will store the payment methods a commerce can offer its customers.

This model is independent: it introduces no ForeignKeys and has no `relationship()` attributes. Consumers (a future `ComercioMediosPago` join table, or similar) will reference this table in a later subphase. The user supplied the column body directly, so the surface area is fully specified.

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives under purpose-specific subdirectories of `backend/` (here: `backend/models/`).
- Implement only what is explicitly requested.
- Dev DB `supernova` and test DB `supenova_test`; both will eventually contain `medios_pago` once a future subphase configures Alembic.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy `MediosPago` model whose column set exactly matches the user-supplied body.
- Re-export `MediosPago` from `backend/models/__init__.py` so consumers can import it from a stable path.
- Mark `codigo` unique + indexed (it is the natural lookup key on every order-intake path).
- Keep the surface area minimal: no `__repr__`, no validators, no relationships.

**Non-Goals:**

- Alembic migrations (a separate subphase).
- Seed rows (`EFECTIVO`, `TRANSFERENCIA`, `MERCADO_PAGO`, etc.).
- Any join table that ties `Comercio` to its accepted payment methods.
- Any service, repository, API endpoint, or DTO layer.

## Decisions

**D1 — File: `backend/models/medios_pago.py` and re-export from `backend/models/__init__.py`.**
Per the convention established in Subphases 1.1 and 1.2: one purpose per file under `backend/models/`, `__init__.py` re-exports so consumers `from backend.models import MediosPago`.

**D2 — ORM style: SQLAlchemy 2.0 typed declarations (`Mapped[…]` + `mapped_column(…)`).**
Matches the style used in Subphase 1.2 (and the user's spec for this model). `EstadoComercio` in 1.1 used the older `Column(…)` style; both compile to the same `Table` metadata, so the inconsistency is purely cosmetic.

**D3 — `__tablename__ = "medios_pago"` exactly as supplied.**
The Spanish-snake-case identifier matches the convention used by `estado_comercio` and `comercio` (no English pluralization rules applied). We preserve it unchanged.

**D4 — Preserve `activo` with both `default=True` and `server_default="true"`.**
The user provided both. `default=True` covers Python-side inserts via SQLAlchemy ORM; `server_default="true"` ensures the column is populated at the database layer (e.g., raw inserts from migrations, psql, ORMs that bypass attribute defaults). PostgreSQL accepts the string `"true"` as a boolean literal in a column default expression.

**D5 — Preserve all column constraints exactly as supplied.**

- `codigo`: `String(50)`, `nullable=False`, `unique=True`, `index=True` — natural lookup key; uniqueness prevents duplicate codes.
- `descripcion`: `String(100)`, `nullable=False` — human-readable label.
- `activo`: `Boolean`, `nullable=False`, `default=True`, `server_default="true"` — soft-disable flag.
- `fecha_alta` / `fecha_ultima_modificacion`: timezone-aware DateTime, `server_default=func.now()`; the latter additionally carries `onupdate=func.now()`. We deliberately do **not** add a Python-side `default=` for these — the database owns them, mirroring Subphase 1.2.

**D6 — No `__repr__`, no validators, no relationships.**
Per "Implement only what is explicitly requested" and "Avoid overengineering". Adding a `__repr__` is a debug convenience not requested; validators belong in a service layer (future subphase); relationships are deferred to the join-table subphase.

## Risks / Trade-offs

- **[Risk] No seed rows yet — every `INSERT` requires the caller to provide all columns explicitly.** → Mitigation: not a problem today (no inserts happen before migrations and seeding land). Future subphases that insert catalog rows must seed `medios_pago` first.
- **[Risk] `activo` default behaviour is invisible to consumers unless they read it.** → Mitigation: documented in the spec. If a future requirement calls for explicit deactivation semantics (e.g., a partial unique index for "only one active row per code"), it can be added as an explicit delta later.
- **[Trade-off] Mixing SQLAlchemy declarative styles** (`Column(…)` in 1.1, `Mapped[…]` in 1.2 and here). → Acceptable: both compile to the same `Table` metadata; no runtime impact, no migration impact.

## Migration Plan

Not applicable. No migration is generated, applied, or rolled back in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test`.

## Open Questions

- None for this subphase. The next subphases implied by the model:
  1. The Alembic revision that creates `medios_pago` (and `estado_comercio`, `comercio`) on both `supernova` and `supenova_test`.
  2. Seed rows for `medios_pago` (`EFECTIVO`, `TRANSFERENCIA`, `MERCADO_PAGO`, etc.).
  3. A `ComercioMediosPago` (or equivalent) join model that ties a commerce to the payment methods it accepts.
