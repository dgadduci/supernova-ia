## Context

Subphase 2.1 (Comercios) shipped the FastAPI infrastructure and the first vertical slice: `backend/main.py`, `backend/dependencies.py`, `GET /health`, three comercio endpoints under `Router → Service → Repository → Model`. Subphase 2.2 is the next vertical slice, anchored on the `EstadoComercio` model. `EstadoComercio` is the smallest catalog root — only `id` and `estado` columns — but it sits at the top of the FK chain (`Comercio.estado_id` references it), so it must be reachable through HTTP before any future slice exposes `estado` references on other resources.

The Phase 2 General Rules apply unchanged (sync FastAPI / Uvicorn / SQLAlchemy sessions; no generic abstractions until ≥ 2 resources need them; tests against `supernova_test` only; minimum tests required; no model changes; no Alembic migrations; one resource per subphase).

Constraints inherited from the prior subphase:

- Per-request SQLAlchemy session via FastAPI dependency using `yield` (in `backend/dependencies.py`).
- Pydantic `from_attributes=True` on response schemas for ORM serialization.
- Domain exceptions in the service layer (`ComercioNotFound` etc.); router translates to HTTP status codes.
- Repository never calls `commit()` / `rollback()`; service owns both.
- Integration tests override `get_session` via `app.dependency_overrides` against `supernova_test`.

## Goals / Non-Goals

**Goals:**

- Expose three CRUD endpoints over `EstadoComercio` (`GET /estados-comercio`, `GET /estados-comercio/{id}`, `POST /estados-comercio`) under the same layering and exception-mapping patterns as Subphase 2.1.
- Replace the `### Subphase 2.2 — TBD` placeholder in `openspec/specs/project.md` with the implemented subphase entry, following the `### Subphase Template` shape.
- Add the minimum integration tests against `supernova_test` to cover the seven scenarios listed in the proposal.

**Non-Goals:**

- Update, delete, pagination, authentication, nested-resource endpoints.
- Exposing `estado` references inside `ComercioResponse` or other resource responses (a future subphase can add nested read endpoints if needed).
- Modifying the `EstadoComercio` model.
- Generating a new Alembic migration.
- Generic repositories, generic CRUD services, or any other abstraction that would anticipate other resources.

## Decisions

- **D1 — Three endpoints, no more.** `GET /estados-comercio` (list ordered by id), `GET /estados-comercio/{estado_comercio_id}` (one, 404 if missing), `POST /estados-comercio` (create, 201 on success, 409 on duplicate `estado`). No update, no delete — the seed already loads the canonical catalog rows (Subphase `seeds-estado-comercio`); runtime mutation is out of scope for this slice.
- **D2 — `estado` uniqueness enforced at the service layer.** The model has no DB-level unique constraint on `estado`. The service calls `repo.get_by_estado(...)` before insert and raises `DuplicateEstado` (mapped to HTTP 409) on collision. Mirrors the whatsapp/slug uniqueness pattern in Subphase 2.1.
- **D3 — Two Pydantic schemas.** `EstadoComercioCreate` (single `estado` field, optional in the future but for now just the one required text field with whitespace trim) and `EstadoComercioResponse` (full persisted column set with `from_attributes=True`).
- **D4 — Five repository methods.** `list_all`, `get_by_id`, `get_by_estado`, `create`, `estado_in_use`. The `estado_in_use` method exists for the service to refuse `DELETE` operations in a future subphase, but it is not exposed via HTTP in this subphase. The method is included now because the service contract is simpler when the lookup exists, even though it is unused today; removing it would force a future deletion subphase to add it back.
- **D5 — Same file layout as Subphase 2.1.** `routers/estados_comercios.py`, `schemas/estado_comercio.py`, `repositories/estado_comercio_repository.py`, `services/estado_comercio_service.py`. No new `services/exceptions.py` — the four new domain exceptions extend the existing `backend/services/exceptions.py`.
- **D6 — Tests live alongside Subphase 2.1 tests.** `backend/tests/api_smoke.py` grows with the new scenarios. No new test module: a single suite keeps the dependency-override fixture and the isolation helpers in one place.
- **D7 — `project.md` Subphase 2.2 entry condensed per `completed-subphase-context-condensation` from day one.** Even though this is the active subphase, the entry written here follows the same condensed shape that was applied retrospectively to Subphase 2.1. This keeps the active/future boundary consistent and means the post-completion cleanup is a no-op.

**Alternatives considered:**

- A single `Status` schema shared by Create and Response: rejected — `EstadoComercio` has only one persisted text field, so Create and Response are nearly identical; per project.md rule "Create separate create, update and response schemas only when their structures differ", two schemas still preferred because the rule is structural, not value-based.
- Idempotent `POST` (upsert on duplicate `estado`): rejected — the Phase 2 General Rules say "implement one resource per subphase"; upsert semantics belong to a future refinement.
- Returning the full commerce list when an estado is requested (eager loading): rejected — out of scope for this subphase; the `estado_id` FK in `Comercio` already supports a future nested endpoint.

## Risks / Trade-offs

- **[Risk] `estado_in_use` repository method exists but is unused today.** → Mitigation: it has zero callers; a future subphase that adds `DELETE /estados-comercio/{id}` will use it. If the future subphase never materializes, the method is dead code but harmless and small.
- **[Risk] Test suite grows in a single file.** → Mitigation: project.md rule says "do not create separate unit tests for schemas, repositories, and services when the endpoint integration test already covers the required behavior"; the single-file pattern matches that rule and stays short until it needs splitting.
- **[Trade-off] The condensed Subphase 2.2 entry written today will not grow as long as the implementation stays minimal.** Acceptable — the `completed-subphase-context-condensation` rule applies retrospectively only when an entry is completed; active subphases may need their full content while being built. Once marked `[x]`, the entry will be condensed again if it has grown.

## Migration Plan

Not applicable. No Alembic migration is generated by this change. The `EstadoComercio` table already exists from the initial Alembic migration (`7f9610191db8`).

## Open Questions

- None for this subphase. Future subphases (e.g., DELETE endpoints, nested `estado` reads inside `ComercioResponse`) inherit the same layering and exception-mapping patterns established here.
