## Context

Phase 1 closed with 11 SQLAlchemy models, an Alembic initial migration, and 11 idempotent seed scripts populating both `supernova` and `supernova_test`. The next phase (Phase 2 — FastAPI API, per `openspec/specs/project.md`) introduces the HTTP layer incrementally, one resource per subphase. This change covers Subphase 2.1 — the minimum FastAPI infrastructure plus the first vertical slice, anchored on the existing `Comercio` model.

Constraints inherited from project.md Phase 2 rules:

- Sync FastAPI, Uvicorn, and SQLAlchemy sessions.
- Strict layering: `Router → Service → Repository → SQLAlchemy Model → PostgreSQL`.
- One resource per subphase. Subphase 2.1 = Comercios only.
- No modifications to existing models. No Alembic migrations.
- `backend/main.py` is limited to app creation, router registration, app-level config, and `/health`.
- `backend/dependencies.py` provides one SQLAlchemy session per request via `yield`, closed after.
- Routers handle only HTTP concerns (routes, params, schemas, status codes, dependency injection, exception translation).
- Pydantic schemas handle request validation and response serialization. Create separate create/update/response schemas only when their structures differ.
- Services contain business rules, coordinate repositories, and control commit/rollback. Raise domain exceptions (not HTTPException).
- Repositories contain DB access only, using SQLAlchemy ORM or `select()`. Never commit/rollback.
- No raw SQL unless SQLAlchemy cannot reasonably express the operation.
- All DB tests run against `supernova_test`.
- No generic repositories, generic CRUD services, or reusable abstractions unless ≥ 2 implemented resources require them.
- No separate unit tests for schemas, repositories, or services when the endpoint integration test already covers the behavior.
- Refactor only files directly required by the active subphase.

## Goals / Non-Goals

**Goals:**

- Bootstrap a sync FastAPI application served by Uvicorn.
- Expose `GET /health` returning `{"status": "ok"}`.
- Provide one SQLAlchemy session per request, closed after the request, via a FastAPI dependency.
- Expose three commerce endpoints: `GET /comercios`, `GET /comercios/{comercio_id}`, `POST /comercios`.
- Apply request validation (whitespace trim, empty-rejection, estado existence check, uniqueness of whatsapp and slug) in the service layer.
- Translate domain exceptions to HTTP status codes in the router layer (404, 409).
- Run the minimum integration tests against `supernova_test` to verify the seven scenarios listed in the proposal.

**Non-Goals:**

- Update, delete, logical deletion, pagination, authentication, or nested-resource endpoints.
- New Alembic migrations or any modification to the existing `Comercio` / `EstadoComercio` models.
- Exposing `metodos_entrega` or `medios_pago` associations on any commerce response.
- A generic repository or generic CRUD service that would anticipate other resources.
- Unit tests for schemas, repository, or service layers (the integration tests cover them).
- Any other Phase 2 subphase (Productos, MediosPago, etc.) — those land in their own OpenSpec changes.

## Decisions

**D1 — Sync stack throughout.** Sync FastAPI + sync SQLAlchemy 2.0 sessions. No async engines, no async routes. Matches the project's existing model layer (which uses `declarative_base()` with sync `Mapped`/`mapped_column`) and avoids introducing a second concurrency model just for the API tier.

**D2 — Strict four-layer split.** Router owns HTTP translation only; Service owns business rules + transaction control; Repository owns DB access only (no commit/rollback); Model is the existing SQLAlchemy class. Each layer has exactly one responsibility and one test surface. This matches project.md Phase 2 rules verbatim.

**D3 — Domain exceptions in the service layer.** `ComercioNotFound`, `EstadoComercioNotFound`, `DuplicateWhatsapp`, `DuplicateSlug` (all defined in `backend/services/exceptions.py`). The router catches them and maps to HTTP status codes. This keeps the service layer free of HTTP concerns and lets future resources reuse the same exception patterns.

**D4 — Schemas limited to `ComercioCreate` and `ComercioResponse`.** No update schema, no filter schema, no nested schemas for the `estado` relationship. `ComercioResponse` carries the full commerce field set declared in the proposal (lifecycle fields included; relationship fields excluded).

**D5 — `ComercioCreate` accepts the same set as `ComercioResponse` minus lifecycle fields.** `zona_horaria`, `moneda`, `idioma` are optional on input; the model defaults are applied when omitted. The service trims surrounding whitespace from every text field and rejects empty required strings before any DB call.

**D6 — Repository methods scoped to this subphase only.** `list_all`, `get_by_id`, `get_by_whatsapp`, `get_by_slug`, `create`, `estado_exists`. The two `get_by_*` methods exist solely to support the service's uniqueness checks; they are not used directly by the router.

**D7 — Service is the only place that calls `commit()` or `rollback()`.** Repository methods return ORM objects; service applies business rules, calls repository methods, commits on success, rolls back on DB error. Router never touches a session for transaction control.

**D8 — Session dependency is the only place SQLAlchemy sessions are constructed.** `backend/dependencies.py` exposes a single `get_session` generator that yields a session and closes it. Router endpoints depend on it via `Depends(get_session)`. Service receives the session through the router's dependency injection.

**D9 — `/health` does not touch the database.** It returns a static payload. No session, no model, no Pydantic. Keeps the liveness probe cheap and avoids coupling infrastructure health to DB availability.

**D10 — Integration tests use the minimum fixtures required to isolate `supernova_test`.** Tests target the seven scenarios enumerated in the proposal. They do not seed the entire catalog; they create only the rows they need and clean up after themselves, so they can run in any order without interference.

**Alternatives considered:**

- A generic `BaseRepository[T]` for CRUD across resources: rejected — project.md explicitly forbids this until ≥ 2 resources require it.
- Async FastAPI: rejected — would require an async SQLAlchemy engine and async session machinery that the rest of the project does not use.
- Returning `dict` instead of `ComercioResponse` from endpoints: rejected — `response_model` is required by project.md.

## Risks / Trade-offs

- **[Risk] `supernova_test` shared state corrupts tests.** → Mitigation: each test creates rows with unique CUITs/whatsapp/slugs (timestamp-based suffixes) and cleans up via the `TestClient` session lifecycle. Tests are written so they do not depend on data seeded by previous tests.
- **[Risk] Service exceptions leak through if the router's exception mapping is incomplete.** → Mitigation: the router declares explicit handlers for each domain exception class; any uncaught exception surfaces as a 500 and is caught by the integration tests (which assert success paths only — uncovered 500s would surface in the completion check).
- **[Trade-off] Repository's `get_by_whatsapp` and `get_by_slug` exist solely for service-side uniqueness checks.** This is intentional duplication of the unique-key enforcement (DB unique constraints also exist via the model's indexes) — it lets the service return a typed domain exception instead of catching `IntegrityError`.
- **[Trade-off] No `__init__.py` proliferation.** Only added where the existing package structure requires it; some `backend/routers/`, `backend/services/`, etc. may already have them from Phase 1, others not. The implementation checks for existing files first.
- **[Trade-off] `/health` is intentionally not authenticated and not versioned.** Future subphases may add a `/healthz` vs `/readyz` split and a versioned prefix; out of scope here.

## Migration Plan

Not applicable. No schema changes, no Alembic migration is generated by this change. The change is purely additive at the Python layer.

## Open Questions

- None for this subphase. Future subphases (Productos, MediosPago, MetodosEntrega, Categorias, Presentaciones, Precios, etc.) inherit the same layering and exception-mapping patterns established here.
