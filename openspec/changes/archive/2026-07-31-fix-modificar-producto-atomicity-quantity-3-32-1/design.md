## Context

Subphase 3.32 (`modificar-producto-end-to-end-3-32`) wired `modificar_producto` end-to-end through the same architectural seams as `agregar_producto` and `quitar_producto`: static contract → recognizer → initial orchestration → staged pending-context resolution → handler → deterministic response builder → response orchestrator → transactional incoming-message flow → HTTP endpoint → interactive CLI. The dispatch arms in `initial_intent_dispatcher`, `pending_context_dispatcher`, `pending_context_execution`, `incoming_message_response_orchestrator`, and `context_type_resolver` route `modificar_producto` correctly, and `PedidoProductoService.modify_product` was introduced as the single atomic mutation entry point with the required pre-mutation validations and consolidation semantics.

Real CLI testing against the running local FastAPI app exposed two defects that violate the atomic quantity-preserving contract established for this flow:

- **Error 1 — Source quantity is not preserved when destination quantity is omitted.** Sending `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with 4 Empanadas de Verdura currently removes all 4 source units but only adds 1 Empanada de Carne Picante. The destination quantity must equal the transferred source quantity.
- **Error 2 — Source is mutated before destination validation.** Sending `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido with 5 Empanadas de Jamón y Queso (where `caramelo` is not in the comercio catalog) currently removes the source line and leaves the Pedido empty. The modification must be one atomic business operation; any failed destination validation must leave the Pedido exactly as it was before the message.

The existing handler spec (`modificar-producto-handler/spec.md`) and the existing service code already state the correct rules — explicit `cantidad_a_modificar` derivation and validation-before-mutation — but the implementation does not enforce them end-to-end. Specifically:

- The destination quantity is currently derived from the explicit `cantidad` in `resolved_data`, but when the message omits a quantity and the recognizer returns `None`, the resolver and handler must keep that omission rather than substituting 1. The defect is that the source quantity is not re-read at execution time and the omitted-quantity semantics are not preserved across turns.
- Destination validation currently runs after the source quantity has been decremented, so an unknown destination (e.g. `caramelo`) leaves the Pedido with the source line removed. The defect is that the validation order allows source mutation to happen before destination validation completes.

The existing `PedidoProductoRepository` already exposes the minimum surface required for atomic modification (`get_for_pedido`, `decrement`, `delete`, `increment`, `create_with_price_snapshot`); `PedidoProductoService.modify_product` already performs the documented pre-mutation validations. The transactional wrapper (`process_incoming_message_transactional`) is the sole commit/rollback owner.

## Goals / Non-Goals

**Goals:**

- Enforce the authoritative quantity rule end-to-end: `cantidad_a_modificar` is the explicit `cantidad` when supplied, otherwise the current source-line quantity re-read at execution time; destination quantity always equals `cantidad_a_modificar`; never defaults to 1.
- Enforce validation-before-mutation: every destination validation (recognition, candidate validity, active state, availability, commerce ownership, price availability, duplicate/consolidation lookup, source/destination equivalence, quantity) must complete before any source row is mutated.
- Produce exactly one `ProcessedIntent` and exactly one `CustomerResponse` per modification message — never a remove response followed by an add response.
- Preserve the destination line's stored price snapshot when the destination PedidoProducto already exists; create a new line with the current destination price snapshot otherwise; never look up the destination price after the source has been mutated.
- Preserve the existing corrected pending-context lifecycle: definitive `rejected` clears, `executed` clears, `failed` preserves, raised exceptions propagate for rollback.
- Preserve the existing `agregar_producto` and `quitar_producto` flows and the unique `(pedido_id, producto_presentacion_id)` invariant.

**Non-Goals:**

- No new HTTP endpoint, no CLI redesign, no extra confirmation turn, no LLM beautification, no Twilio / WhatsApp adapter, no WebSocket, no HTML.
- No DB schema change, no Alembic migration, no new public method on repositories unless strictly required, no new intent.
- No redesign of the existing intent framework; the change stays inside the seams established by subphases 3.19, 3.31, and 3.32.
- No automatic sync of main specs and no automatic archive — both remain explicit user commands (`/opsx:sync`, `/opsx:archive`).

## Decisions

### 1. Re-read the source quantity at execution time when `cantidad` is omitted

`execute_modificar_producto` re-reads the current `PedidoProducto` row's quantity at the moment of execution and uses it as the omitted-quantity transfer value. The re-read happens inside the same transaction boundary, after all destination validations have passed but before the source mutation runs. The recognizer, the initial orchestrator, and the pending-context resolver never substitute a default of 1 for an omitted quantity; they persist `cantidad is None` as the omitted-quantity sentinel across turns.

**Rationale:** The defect is that the omitted-quantity semantics are not preserved end-to-end. The fix is to treat the re-read of the source quantity at execution time as the authoritative transfer value, never the recognizer's stale snapshot.

**Alternatives considered:**
- *Default destination quantity to 1 in the recognizer or the initial orchestrator.* Rejected: violates the spec rule "Do not default destination quantity to 1" and produces Error 1.
- *Re-validate the explicit quantity on every turn but skip the re-read.* Rejected: leaves the omitted-quantity path unfixed and re-introduces the defect.
- *Carry the source quantity in the pending context.* Rejected: stale across turns; the spec rule is to re-read at execution.

### 2. Reorder `PedidoProductoService.modify_product` so all destination validations precede any source mutation

`modify_product` runs the validations in this strict order: load and validate the draft Pedido → load and validate the source PedidoProducto → compute `cantidad_a_modificar` (explicit or re-read full source quantity) → validate `cantidad_a_modificar` does not exceed source quantity → load and validate the destination `ProductoPresentacion` (existence, same comercio, active, available, presentacion active) → equivalent-modification guard → destination consolidation lookup → destination price availability lookup. Only after every validation succeeds does the service decrement or delete the source and create or increment the destination. The service never commits, rolls back, flushes, refreshes, expires, or begins.

**Rationale:** Error 2 is caused by source mutation happening before destination validation completes. The fix is a strict pre-validation order with no commit between source removal and destination addition.

**Alternatives considered:**
- *Wrap the two repository calls in a nested SAVEPOINT.* Rejected: the existing transaction wrapper already owns the boundary; introducing SAVEPOINTs adds complexity without fixing the defect.
- *Have the handler short-circuit on unknown destination before calling the service.* Rejected: duplicates business logic and leaks it out of the service layer; the recognizer can return destination candidates without guaranteeing their validity.
- *Move destination validation into the recognizer.* Rejected: the recognizer is read-only and does not own business rules.

### 3. Authoritative quantity rule codified in one place

The quantity-derivation rule lives in exactly one place: a private helper inside `PedidoProductoService.modify_product` that returns `cantidad_a_modificar` from the explicit `cantidad` argument or the re-read source quantity. The handler, the recognizer, the initial orchestrator, and the pending-context resolver never compute or substitute a quantity; they only pass through the explicit value or the `None` sentinel.

**Rationale:** The defect is exacerbated by quantity-substitution logic distributed across the pipeline. Concentrating the rule in the service makes it auditable and prevents drift.

**Alternatives considered:**
- *Encode the rule in the contract.* Rejected: the contract declares the optional field shape; the derivation rule is service business logic.
- *Encode the rule in the handler.* Rejected: the handler is intentionally thin and delegates to the service.

### 4. Equivalent-modification and consolidation rules preserved

Equivalent-modification (`source.producto_presentacion_id == destination.producto_presentacion_id`) continues to return `rejected` with `reason="equivalent_modification"` before any mutation. Consolidation (destination PedidoProducto already exists for the same `producto_presentacion_id` in the same Pedido) continues to increment the existing line in place and preserve its stored price snapshot. The price snapshot for a new destination line is read from the current active `Precio` row, never re-read after the source has been mutated.

**Rationale:** Preserves the existing 3.32 invariants and prevents drift from subphase 3.30.3.

**Alternatives considered:**
- *Re-read the price snapshot at execution time even when the destination line already exists.* Rejected: violates the established snapshot-preservation rule and would overwrite a stored price with the latest catalog price.
- *Force the destination to be a new line.* Rejected: violates the consolidation invariant and would create duplicate `PedidoProducto` rows for the same `(pedido_id, producto_presentacion_id)` pair.

### 5. Single `ProcessedIntent` and single `CustomerResponse` invariants

`process_initial_modificar_producto` and `pending_context_dispatcher.resolve_product_modification` return exactly one `ProcessedIntent` per modification message. `execute_modificar_producto` returns exactly one `ProcessedIntent`. The handler never invokes `execute_quitar_producto` or `execute_agregar_producto`. `incoming_message_response_orchestrator` translates the single outcome into one `CustomerResponse` through `build_modificar_producto_response`. No code path produces a remove response followed by an add response.

**Rationale:** The defect manifests as a "remove + add" decomposition. The fix is to enforce that the entire pipeline emits one outcome and one response per modification.

**Alternatives considered:**
- *Allow the orchestrator to emit two `ProcessedIntent` entries for the modification.* Rejected: violates the spec rule "One modification message must produce one final `ProcessedIntent`" and the customer-facing UX requirement.
- *Suppress intermediate responses by post-processing the response list.* Rejected: hides the defect instead of fixing it; brittle.

### 6. Pending-context preservation of omitted-quantity semantics

When the destination is ambiguous and the source is unique, `process_initial_modificar_producto` and `resolve_product_modification` persist `cantidad is None` (the omitted-quantity sentinel) — not a substitute of 1 — together with the resolved source ID and the current `stage`. When the destination finally resolves, the handler re-reads the current source quantity and uses it as the omitted-quantity transfer value, validating it against any explicit `cantidad` already persisted.

**Rationale:** The defect can re-emerge across turns if the orchestrator substitutes 1 for an omitted quantity during refinement. Persisting the `None` sentinel and re-reading at execution time keeps the semantics correct across multi-turn flows.

**Alternatives considered:**
- *Persist the recognizer's quantity as 1 when the user omitted it.* Rejected: violates the spec rule and re-introduces Error 1.
- *Persist `source.cantidad` in the pending context.* Rejected: stale across turns.

### 7. Concurrency / stale-state rule preserved

If the source line changed between resolution and execution (e.g. another `agregar_producto`/`quitar_producto`/`modificar_producto` modified it inside the same transaction), the re-read at execution time detects the divergence. The service then re-validates the source against the current quantity, applies the equivalent-modification guard, and translates stale state into the existing appropriate business exception. No retry logic is introduced.

**Rationale:** Mirrors the existing 3.32 rule and the corrected lifecycle already enforced for `agregar_producto` and `quitar_producto`.

**Alternatives considered:**
- *Introduce optimistic locking on `PedidoProducto`.* Rejected: out of scope; the existing transactional wrapper is sufficient.
- *Add retry logic.* Rejected: explicitly forbidden by the spec.

### 8. Deterministic response matrix for the corrected outcomes

`build_modificar_producto_response` extends the deterministic message matrix without LLM involvement:

- Executed full transfer (omitted quantity): `Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.`
- Executed partial transfer (explicit quantity): `Cambié 2 Empanadas de Verdura por 2 Empanadas de Carne Picante. Quedan 2 Empanadas de Verdura.`
- Executed consolidated: `Cambié 4 Empanadas de Verdura por Empanadas de Carne Picante. Ahora tenés 6 Empanadas de Carne Picante.`
- Unknown destination: `No encontré el producto de reemplazo. Tu pedido no fue modificado.`
- Unavailable destination: `El producto de reemplazo no está disponible. Tu pedido no fue modificado.`
- Excess quantity: `Solo tenés 3 Empanadas de Verdura para cambiar. Tu pedido no fue modificado.`

No technical detail, no DB IDs, no LLM call.

**Rationale:** The defect is partly customer-facing: the user must be told that the Pedido was not modified when validation fails. Concise deterministic Spanish messages close the loop.

**Alternatives considered:**
- *LLM-generated response.* Rejected: out of scope and inconsistent with the established response builder pattern.
- *Reuse the existing `Ese producto no está disponible como reemplazo.` and `Solo tenés N para cambiar.` messages verbatim.* Rejected: the spec mandates explicit confirmation that the Pedido was not modified; the new messages add that confirmation.

### 9. Repository surface unchanged

`PedidoProductoRepository` continues to expose the minimum surface required for atomic modification (`get_for_pedido`, `decrement`, `delete`, `increment`, `create_with_price_snapshot`, `get_by_pedido_and_producto_presentacion`, `current_precio`, `pedido`, `producto_presentacion_exists`). No new public methods are introduced. The repository methods continue to perform only the staged ORM change they advertise and never commit or rollback.

**Rationale:** Mirrors the established 3.32 pattern; concentrates business rules in the service; keeps handlers and resolvers thin.

**Alternatives considered:**
- *Add a new `modify` method on the repository.* Rejected: violates the rule that repositories are DB-only; concentrates business logic in the wrong layer.
- *Add a `get_current_cantidad` method.* Rejected: `get_for_pedido` already returns the row; the service can read `.cantidad` directly.

### 10. Test surface scoped to the defect matrix

The change adds focused tests for `modify_product` (validation-before-mutation, authoritative quantity derivation, consolidation, equivalent-modification guard, price-snapshot rules, transactional boundary), for `execute_modificar_producto` (single `ProcessedIntent` invariant, re-read of source quantity when omitted, no decomposition), for `process_initial_modificar_producto` and `resolve_product_modification` (omitted-quantity persistence across turns), and for `build_modificar_producto_response` (every new message). It extends the end-to-end integration test with the real HTTP regression scenarios (Error 1 and Error 2) and the full atomic-quantity matrix described in the spec (A through V). It re-runs the `agregar_producto` and `quitar_producto` regressions and the CLI conversation regression.

**Rationale:** The defects are real and the regression matrix must cover them end-to-end. Focused tests catch unit-level regressions; the end-to-end test catches the integration-level defects.

**Alternatives considered:**
- *Add only end-to-end tests.* Rejected: hides the unit-level invariants and makes future drift harder to diagnose.
- *Refactor existing tests.* Rejected: explicitly out of scope; regression must remain green unchanged where possible.

## Risks / Trade-offs

- **Drift in quantity-derivation logic across the pipeline** → Concentrate the rule in one helper inside `PedidoProductoService.modify_product`; forbid quantity substitution in the recognizer, initial orchestrator, and pending-context resolver; add focused tests for each layer.
- **Stale source quantity across turns** → Re-read `PedidoProducto.cantidad` at execution time inside the same transaction; never persist the source quantity in the pending context; never cache it in the resolver.
- **Source mutation racing destination validation** → Reorder `modify_product` so destination validation runs entirely before any source mutation; never commit between the two operations; never issue SQLAlchemy queries directly in the handler.
- **Equivalent modification accepted by accident** → Equivalent-modification guard stays the first destination validation, before any source mutation; pre-mutation check compares `source.producto_presentacion_id` to `destination.producto_presentacion_id`; equality returns `rejected` with deterministic reason.
- **Destination price drift after source mutation** → Price snapshot read happens once, before the source mutation; existing destination line never re-priced; new destination line created with the current catalog price; the source line price is never read or written by the modify path.
- **Stale `agregar_producto` or `quitar_producto` flow** → Existing 3.19 and 3.31 regressions must remain green unchanged; no public surface change to `add_or_increment`, `delete`, or `list_by_pedido`; the corrected lifecycle still applies.
- **CLI table rendering after a rejected modification** → The CLI continues to render the current order table after Error 2 without modification; the regression test asserts the table shows `Empanada de Jamón y Queso | Unidad | 5` unchanged.
- **Customer-facing message drift across the corrected outcomes** → The response builder is a single deterministic Python function with no LLM involvement; new messages follow the existing message templates; the message matrix is documented in the spec.
- **Inheritance of `quitar_producto` or `agregar_producto` accidentally triggered for `modificar_producto`** → The handler never calls `execute_quitar_producto` or `execute_agregar_producto`; the contract registry, the initial dispatcher, the pending-context dispatcher, the pending-context execution, and the response orchestrator keep their existing `modificar_producto` arms; the `ContextType.PRODUCT_MODIFICATION` route is strictly separated from `PRODUCT_SELECTION` and `ORDER_LINE_SELECTION`.

## Migration Plan

No DB migration is required. The change is source-only and is rolled out by deploying the corrected `PedidoProductoService.modify_product`, the corrected `execute_modificar_producto`, the corrected initial-orchestration and pending-context rules, and the extended response matrix.

Rollback is achieved by reverting the corrected service method, handler, orchestrator, and response builder to their 3.32 behavior. After rollback, `modificar_producto` reverts to the current defective behavior (Error 1 and Error 2). No data needs to be migrated or backfilled.

The change remains active under `openspec/changes/fix-modificar-producto-atomicity-quantity-3-32-1/` after `/opsx:apply` completes. `/opsx:sync` is manual; `/opsx:archive` is manual; the agent must not run either automatically.

## Open Questions

None. The active subphase spec leaves the defect matrix, the authoritative quantity rule, the validation-before-mutation order, the consolidated response matrix, the integration seams, and the regression scope fully specified. Implementation only needs to honor them.