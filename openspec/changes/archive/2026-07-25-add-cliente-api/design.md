## Context

The customer identity is the missing half of the ordering picture. Phase 1 created every commerce-side model; Phase 2 wired them into FastAPI. Subphase 2.11 introduced `pedido`, but the pedido spec explicitly deferred any `session` relationship until a `session` model exists. That `session` model (Subphase 2.13) needs `id_cliente` as a non-null FK, so a `Cliente` model must land first. This subphase is that prerequisite.

## Goals / Non-Goals

**Goals:**

- Persist a `cliente` row with `whatsapp` as the canonical identifier (unique, E.164).
- Capture optional display data: `nombre`, `domicilio`.
- Expose five sync FastAPI endpoints (create, get-by-id, get-by-whatsapp, update, activate/deactivate) following the established layering.
- Apply a single Alembic migration to both `supernova` and `supernova_test`.
- Normalize `whatsapp` in the service before persistence; reject duplicates at the service layer with HTTP 409.
- Deactivate a cliente via a dedicated endpoint (PATCH or PUT of `activo`); update endpoint leaves `activo` untouched unless explicitly supplied.

**Non-Goals:**

- No `Session` relationship or any session logic — owned by Subphase 2.13.
- No delete endpoint.
- No pagination, authentication, or filtering.
- No phone-number ownership verification (Twilio/WhatsApp-side concerns).
- No multi-comercio scoping — a cliente is global.

## Decisions

- **D1 — `whatsapp` is the canonical identifier.** Stored as `String(20)`, `unique=True, index=True`. The service normalizes input to E.164 (digits only, leading `+`, country code intact) before any lookup or insert. Two raw inputs that differ only in whitespace or formatting map to the same stored value.
- **D2 — Timestamps use the user's spec naming.** The active subphase spec names the lifecycle columns `created_at` / `updated_at`. This differs from the existing `fecha_alta` / `fecha_ultima_modificacion` convention; we follow the subphase spec verbatim because the user wrote it explicitly. Timezone-aware `DateTime(timezone=True)` with `server_default=func.now()` and `onupdate=func.now()` on `updated_at`.
- **D3 — `nombre` and `domicilio` are nullable strings.** `nombre` `String(150)`, `domicilio` `String(255)`. Both are trimmed by the service; empty-after-trim becomes `None`.
- **D4 — `activo` is a non-null Boolean with default `True`.** `server_default="true"`. The activate/deactivate endpoint flips this single flag without touching other fields.
- **D5 — Update endpoint accepts the mutable subset.** PATCH-style: `nombre`, `domicilio`, and `activo` are mutable; `whatsapp` is **immutable** through this endpoint (changing a customer's phone number is a separate operation, not yet in scope).
- **D6 — Layering.** New files mirror the existing per-resource layout: `backend/routers/clientes.py`, `backend/schemas/cliente.py`, `backend/repositories/cliente_repository.py`, `backend/services/cliente_service.py`. The service owns commit/rollback and the E.164 normalization + duplicate check. The router translates domain exceptions to HTTP errors.
- **D7 — Migration is a single `alembic revision --autogenerate`.** The new model is added to `backend/alembic/env.py` next to the existing 12 imports so autogenerate sees it; the revision creates the `clientes` table only.

## Risks / Trade-offs

- **[Risk] Autogenerate misses the new model.** → Mitigation: import `Cliente` in `backend/alembic/env.py` next to the existing 12 model imports before running `alembic revision --autogenerate`.
- **[Risk] E.164 normalization drifts between writer and reader.** → Mitigation: all write paths (create, future updates) flow through the service's normalizer; read paths return the stored canonical value directly.
- **[Risk] Existing services use `fecha_alta` / `fecha_ultima_modificacion` while this subphase uses `created_at` / `updated_at`.** → Mitigation: documented in D2; only `Cliente` uses the new convention. Future subphases that need to read `Cliente` columns can map explicitly. No model mixing within a single table.
- **[Trade-off] `whatsapp` is immutable through the update endpoint.** → Acceptable for the active subphase: changing a customer's phone is a security-sensitive operation that needs verification (out of scope).

## Open Questions

- None. The schema, endpoint surface, and rules are fixed by Subphase 2.12 in `project.md`.