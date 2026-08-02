## Context

The order entity is the next concrete model the API must persist. Phase 1 already created every catalog, configuration, and join model the order references (`medios_pago`, `metodos_entrega`); Phase 2 has shipped sync FastAPI slices for each of them under the established `Router → Service → Repository → Model` layering. Subphase 2.11 introduces the order itself. No `session` model exists yet, so the `pedidos` table must stand alone — the relationship is deferred.

## Goals / Non-Goals

**Goals:**

- Persist a `pedido` row with nullable payment method, delivery method, and scheduled delivery time.
- Capture order state in an enum that defaults to `borrador` and only advances through defined transitions.
- Expose six sync FastAPI endpoints that follow the established layering.
- Apply a single Alembic migration to both `supernova` and `supernova_test`.
- Reject any modification attempt when `estado_pedido != borrador` with HTTP 409.
- Reject any state transition not in the allowed graph with HTTP 409.

**Non-Goals:**

- No `sessions` relationship — added when the `session` model exists.
- No list endpoint — only create + get-by-id are required by the active subphase.
- No delete endpoint.
- No pagination, authentication, or filtering.
- No product-line items — the order is captured as a header only.

## Decisions

- **D1 — Use a SQLAlchemy native `Enum` column.** `estado_pedido` is declared as `Enum(EstadoPedido, name="estado_pedido")` with values `borrador`, `ingresado`, `preparacion`, `terminado`, `entregado`, `cancelado`. Python `enum.Enum` mirrors the DB values one-to-one. This keeps transitions type-safe at the model layer and PostgreSQL enforces the value set at the DB layer.
- **D2 — State graph lives in the service.** Allowed transitions:
  - `borrador → ingresado | cancelado`
  - `ingresado → preparacion | cancelado`
  - `preparacion → terminado | cancelado`
  - `terminado → entregado`
  - `entregado → (terminal)`
  - `cancelado → (terminal)`
  Any other pair raises `InvalidEstadoTransition` → 409.
- **D3 — Only `borrador` is mutable.** Every update endpoint checks `pedido.estado_pedido == EstadoPedido.BORRADOR`; otherwise raises `PedidoNotEditable` → 409. The create endpoint always writes `borrador`.
- **D4 — Per-field update endpoints keep payloads small.** Each of `set_medio_pago`, `set_metodo_entrega`, `set_fecha_entrega`, and `cambiar_estado` accepts a body with the single field it owns and rejects the others (`extra="forbid"`). This avoids a generic PATCH and keeps the contract explicit.
- **D5 — FKs are `ON DELETE RESTRICT`.** `id_medio_pago` and `id_metodo_entrega` reference catalog rows; deleting a catalog row that is in use by a pedido must fail at the DB level.
- **D5.1 — Declarative relationships to catalogs.** The `Pedido` model declares two `Mapped[...]` relationship attributes following the existing `comercio.py` pattern:
  - `medio_pago: Mapped[MediosPago | None] = relationship(MediosPago)` — back-references `medios_pago.id` (nullable, lazy-loaded; never auto-joined by listing endpoints).
  - `metodo_entrega: Mapped[MetodosEntrega | None] = relationship(MetodosEntrega)` — back-references `metodos_entrega.id` (nullable, lazy-loaded).
  These attributes exist so future subphases (e.g. catalog detail) can traverse the pedido → catalog edge without new joins, but no endpoint exposes them in the active subphase.
- **D5.2 — Service-level FK existence validation.** When the operator supplies a non-null `id_medio_pago` (or `id_metodo_entrega`) on create or update, the service looks up the catalog row via the existing `MediosPago` / `MetodosEntrega` repositories before persisting. A missing id raises `MedioPagoNotFound` / `MetodoEntregaNotFound` → 400 (the request is malformed from the pedido's point of view). This avoids surfacing a raw `IntegrityError` from `flush()`. A `null` value is always accepted (clears the assignment).
- **D6 — `datetime_entrega_programada` is timezone-aware `DateTime(timezone=True)`, nullable.** No default — the value is operator-supplied. The Pydantic schema accepts ISO-8601 with offset and stores UTC.
- **D7 — No `sessions` relationship on `Pedido`.** A future subphase will add `id_session` and the corresponding back-reference.
- **D8 — Migration is a single `alembic revision --autogenerate`.** The new model is added to `backend/alembic/env.py` so autogenerate sees it; the revision creates the `pedidos` table only — no FK changes elsewhere.
- **D9 — Layering.** New files mirror the existing per-resource layout: `backend/routers/pedidos.py`, `backend/schemas/pedido.py`, `backend/repositories/pedido_repository.py`, `backend/services/pedido_service.py`. The service owns commit/rollback and the state-graph rules. The router translates domain exceptions to HTTP errors.

## Risks / Trade-offs

- **[Risk] Autogenerate misses the new model.** → Mitigation: import `Pedido` from the model module inside `backend/alembic/env.py` next to the existing 11 imports before running `alembic revision --autogenerate`.
- **[Risk] Enum value drift between Python and PostgreSQL.** → Mitigation: the Python `EstadoPedido` enum and the SQLAlchemy `Enum(...)` declaration share the exact same string values; a smoke test creates a pedido and reads it back to confirm round-trip.
- **[Risk] Tests depend on `medios_pago` / `metodos_entrega` seed data.** → Mitigation: the integration tests seed the minimum catalogs they need; both databases already carry these seeds from Phase 1.
- **[Risk] Foreign-key violations surface as `IntegrityError` 500s.** → Mitigation: D5.2 forces a service-level existence check on `id_medio_pago` / `id_metodo_entrega` before `flush()`, so missing catalog ids return 400 instead of 500.
- **[Trade-off] Update endpoints are verbose.** → Four PUT endpoints instead of a single PATCH. → Acceptable: keeps the contract explicit and the per-endpoint validation narrow.
- **[Trade-off] `cancelado` is reachable from `borrador`, `ingresado`, and `preparacion` but not from `terminado`/`entregado`.** → Acceptable: matches the operator's mental model — once shipped or delivered, the order is history.

## Open Questions

- None. The state graph and endpoint surface are fixed by Subphase 2.11 in `project.md`.