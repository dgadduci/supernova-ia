## Context

The supernova-ia backend is a Python service that models a multi-commerce ordering system receiving free-text orders via WhatsApp. The Phase 1 roadmap creates the SQLAlchemy model layer before any Alembic migration is generated or applied. This change implements **Subphase 1.1 — EstadoComercio**, the first reference-data entity.

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Python project with a local `venv`; SQLAlchemy is already a known dependency.
- Code files live in purpose-specific subdirectories under `backend/`.
- Implement only what is explicitly requested; no speculative abstractions.
- Dev DB `supernova` and test DB `supernova_test` will both carry every table once migrations run (later subphase).
- All tests must run against `supernova_test`, never `supernova`.
- This change produces **no migration, no service, no API, no seed data**.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy declarative model `EstadoComercio` with columns `id` (integer primary key) and `estado` (non-null string).
- Establish the minimum shared model infrastructure (the declarative `Base`) so future Phase 1 subphases can register additional models without restructuring.
- Keep the surface area tiny: one model file, no helpers, no validators, no relationships.

**Non-Goals:**

- Generating or applying Alembic migrations.
- Seeding `EstadoComercio` rows (active, suspended, etc.).
- Adding a service, repository, or API endpoint for `EstadoComercio`.
- Adding relationships, indices, timestamps, audit fields, or any column beyond what the spec requires.
- Defining every Phase 1 model — only `EstadoComercio`.

## Decisions

**D1 — File layout under `backend/models/`.**
Per the rule "Store code files inside purpose-specific subdirectories under `backend/`". The directory `backend/models/` becomes the home for Phase 1 models, with one model per file. A package `__init__.py` exposes the declarative `Base` and re-exports the models so other modules can import them from a single, stable path.

Layout:
```
backend/
  __init__.py
  models/
    __init__.py          # re-exports Base and the model classes
    base.py              # declarative Base = declarative_base()
    estado_comercio.py   # EstadoComercio model
```

`Base` lives in its own module (`base.py`) so model files can import it without going through the package `__init__`. This avoids the circular import that arises when `__init__.py` defines `Base` AND imports model classes whose modules re-import `Base` from `backend.models`.

Alternatives considered:
- A single `models.py` file with all models — rejected; it would force every later subphase to edit the same file, violating "one purpose per file" intent.
- Defining `Base` inline in `backend/models/__init__.py` and importing it back from model files — rejected because of the circular import it creates as soon as `__init__.py` re-exports any model.

**D2 — Single shared declarative `Base` in `backend/models/base.py`.**
SQLAlchemy requires every model to inherit from a `declarative_base()`. Centralizing in `base.py` (rather than `__init__.py`) breaks the import cycle that would otherwise form when model files import `Base` and `__init__.py` re-exports those models. The next Phase 1 subphase (e.g., `Comercio`) imports `Base` from `backend.models.base` and registers its model — no duplication, no refactor.

Alternatives considered:
- Defining `Base` per model file — rejected; later subphases would create conflicting metadata when both were loaded.
- Defining `Base` in `backend/models/__init__.py` — rejected for the same reason once a second model exists, plus an immediate circular import today.

**D3 — `__tablename__ = "estado_comercio"` (snake_case singular).**
Matches Python identifier conventions and keeps one model = one table semantics. PostgreSQL identifiers are case-folded to lowercase by default, so this is unambiguous.

Alternatives considered:
- Plural `"estados_comercio"` — rejected; adds no value for a small reference table and would diverge from other Phase 1 models if they use singular convention.

**D4 — `id` as `Column(Integer, primary_key=True)`.**
PostgreSQL natively auto-increments integer primary keys when no explicit default is supplied. PostgreSQL `SERIAL`/`IDENTITY` features are not invoked explicitly here; the implicit autoincrement keeps the model declaration minimal.

Alternatives considered:
- `BigInteger` — rejected; no scale reason documented in the spec.
- Explicit `Sequence("estado_comercio_id_seq")` — rejected; redundant with autoincrement for this use case.

**D5 — `estado` as `Column(String, nullable=False)`.**
The spec requires `estado: str`. Using unbounded `String` (no length argument) keeps the model declaration aligned with the spec and avoids prematurely committing to a column length that future requirements may change. `nullable=False` reflects the project's "minimal but correct" posture: every row must have a status.

Alternatives considered:
- `Column(String(50), nullable=False)` — rejected; arbitrary cap not specified.
- Allowing null and encoding "unknown" as a string — rejected; spec calls it a string column, not an optional one.

**D6 — No `__repr__`, no validators, no relationships.**
Per "Implement only what is explicitly requested" and "Avoid overengineering". Adding a `__repr__` is a common convenience, but the spec does not ask for it and the codebase has no examples to follow yet. If debugging requires it later, it will be added alongside actual consumers of the model.

## Risks / Trade-offs

- **[Risk] The table does not yet exist in the database.** → Mitigation: this change produces models only. The very next subphase will configure Alembic against `supernova`/`supernova_test` and apply the migration. Until then, importing the model is safe but no queries can run.
- **[Risk] Future models may need additional shared infrastructure (e.g., a `Base.metadata` binding).** → Mitigation: centralizing `Base` in `backend/models/__init__.py` gives later subphases a single import point; no refactor is required when the next model lands.
- **[Trade-off] `String` without an explicit length is database-portable but not optimized for storage.** → Acceptable for a small reference table; revisit only if a performance requirement appears.

## Migration Plan

Not applicable. No migration is generated, applied, or rolled back in this change. A dedicated migration subphase is intentionally separate so it can be reviewed as a "Critical" change per `AGENTS.md`.

## Open Questions

- None for this change. Future subphases will decide on seed values for `EstadoComercio` rows and on whether to add `__repr__` once the model gains consumers.
