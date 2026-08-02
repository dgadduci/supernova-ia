## Context

The Phase 3 intent pipeline already wires `agregar_producto` end-to-end (3.1 → 3.19) and `quitar_producto` end-to-end (3.20 → 3.31) through the same architecture: static contract → recognizer adapter → context type and resolver → initial intent dispatcher → pending-context dispatcher → ready handler → pending-context close → response builder → customer-response orchestrator → transactional incoming-message flow → local HTTP endpoint → interactive CLI.

`modificar_producto` is an established `IntentName` (3.20), the classifier already returns it (3.22/3.23), and the local HTTP endpoint plus interactive CLI (3.29/3.30) accept it. Today the classifier-integration tests (3.25) confirm `modificar_producto` produces a `ProcessedIntent` with `status="rejected"` and `handler="modificar_producto"` because the dispatcher does not know the intent. There is no contract, no recognizer, no resolver, no handler, and no response builder for it.

The active draft Pedido holds one `PedidoProducto` row per `producto_presentacion_id` (unique index `uq_pedido_producto_presentacion` enforced by subphase 2.14 and consolidated in 3.30.3). `PedidoProductoService` already exposes `add_or_increment`, `add`, `update` (cantidad/observaciones), `delete`, `list_by_pedido`, and `get_for_pedido` with the borrador-only guard and the documented exceptions. Product queries already expose the active and available catalog per comercio through `producto_queries_api`.

The `SESSION_CONTEXT_TYPE` enum has two values today (`PRODUCT_SELECTION` for `agregar_producto`, `ORDER_LINE_SELECTION` for `quitar_producto`). Neither applies: `PRODUCT_SELECTION` resolves against catalog `producto_presentacion_id`; `ORDER_LINE_SELECTION` refines `pedido_producto_id` candidates but never narrows to a catalog `producto_presentacion_id`. `modificar_producto` needs both domains simultaneously, so a third value is required and the existing two must be strictly preserved.

## Goals / Non-Goals

**Goals:**
- Make `modificar_producto` executable end-to-end through the same architectural seams as `agregar_producto` and `quitar_producto`.
- Mutate only `PedidoProducto` rows that already exist in the active draft Pedido. Never reach into the catalog.
- Carry two distinct identifier domains (source: `pedido_producto_id`; destination: `producto_presentacion_id`) through one pending context without overloading a single `candidate_ids` list.
- Support full-line modification, partial modification (cantidad less than source quantity), omitted-cantidad full modification, and explicit-cantidad excess rejection.
- Support multi-turn refinement of source first, then destination, with explicit `source_selection` and `destination_selection` stages.
- Produce deterministic customer responses without LLM beautification.
- Preserve the unique `(pedido_id, producto_presentacion_id)` order-line invariant and existing price snapshots.
- Reuse the existing transactional incoming-message flow and the existing CLI without changes.

**Non-Goals:**
- No `vaciar_pedido`, no `consultar_estado`, no observations edit, no Pedido-level operations.
- No new HTTP endpoint, no CLI change, no extra confirmation turn.
- No DB schema change, no Alembic migration.
- No LLM-driven response generation.
- No Twilio, no WhatsApp adapter, no WebSocket, no HTML.
- No broad refactor of the existing intent framework.

## Decisions

### 1. Two distinct identifier domains, never one list
Source candidates are `PedidoProducto.id` from the active draft Pedido. Destination candidates are `ProductoPresentacion.id` from the active and available catalog of the same comercio. The pending context carries both domains in distinct fields (`source_candidate_ids`, `destination_candidate_ids`) plus an explicit `stage` field (`source_selection` or `destination_selection`). A single overloaded `candidate_ids` list is rejected because tests would not be able to assert domain identity unambiguously.

**Rationale:** Mirrors the spec rule "do not confuse these identifier domains" and the spec rule against overloading one `candidate_ids` list. Keeps the resolver, handler, and response builder free of domain-inference logic.

### 2. New `ContextType` value: `PRODUCT_MODIFICATION`
A new enum value `PRODUCT_MODIFICATION` is added to `SESSION_CONTEXT_TYPE` carrying the modification context structure. It is used exclusively for `modificar_producto` refinement.

**Rationale:** Existing resolvers validate against single domains. A dedicated context type keeps the three flows strictly isolated and prevents accidental inheritance.

### 3. Recognizer scope: source from current order lines, destination from active catalog
The recognizer for `modificar_producto` receives two catalogs:
- source catalog built from `PedidoProductoService.list_by_pedido(session.id_pedido)` — only current order lines.
- destination catalog built from the existing product-query service for the comercio, restricted to active and available `ProductoPresentacion` rows.

The recognizer emits `source_candidate_ids`, `destination_candidate_ids`, and an optional `cantidad` when an explicit positive integer is present in the message.

**Rationale:** Aligns with the business rules "source candidates must come only from current draft Pedido lines" and "destination candidates come only from active and available catalog rows".

### 4. Resolution order: source first, then destination
When both domains are unresolved, the resolver refines source candidates first, then destination candidates. Refinement must:
- operate only within the current candidate set;
- never broaden back to the full Pedido or full catalog;
- reduce candidates monotonically;
- preserve resolved requirements and the optional `cantidad`;
- transition from `source_selection` to `destination_selection` exactly when source becomes unique;
- return `ready` exactly when both domains are unique.

**Rationale:** The application must first establish which existing line is being changed before resolving the replacement. Matches the explicit "Resolution order" rule in the project spec.

### 5. Atomic mutation delegated to a service operation
The new `PedidoProductoService.modify_product(db, pedido_id, pedido_producto_origen_id, producto_presentacion_destino_id, cantidad)` is the single atomic mutation entry point. Repository methods are added for the minimum required operations (`get_for_pedido`, `decrement`, `delete`, `increment`, `create_with_price_snapshot`); service owns the borrador guard, FK rules, commerce ownership, the unique invariant, and price-snapshot logic. The handler never issues SQLAlchemy queries directly and never mutates rows manually.

**Rationale:** Concentrates business rules in one place, mirrors the established pattern of `quitar_producto` (3.31), and keeps the handler thin. The unique `(pedido_id, producto_presentacion_id)` invariant is enforced through reuse of `add_or_increment` for the destination step.

### 6. Quantity semantics enforced in the service, not the handler
- `cantidad` omitted → modify the entire source line.
- `cantidad` < source quantity → decrement source, increment destination.
- `cantidad` == source quantity → delete source, increment destination.
- `cantidad` > source quantity → `rejected` (`quantity_exceeds_source`), no mutation.
- `cantidad` <= 0 → `rejected` (`invalid_quantity`), no mutation.

**Rationale:** The handler validates intent shape; the service enforces quantity rules. Mirrors `quitar_producto` semantics and prevents handlers from accumulating business logic.

### 7. Equivalent source and destination rejected with deterministic message
If the source line already uses the same `producto_presentacion_id` as the destination, the service returns `rejected` with reason `equivalent_modification` and message `Ese producto ya tiene esa presentación en tu pedido.`. No mutation occurs.

**Rationale:** Explicit spec rule. Avoids a no-op mutation path and prevents a 0-row write from being reported as a successful modification.

### 8. Price snapshot rules
- If the destination line already exists in the same Pedido → preserve its stored price snapshot (do not overwrite).
- If the destination line does not exist → create it with the current destination catalog price snapshot from the active `Precio` row.
- The source line price is irrelevant after full deletion and remains unchanged after partial decrement.

**Rationale:** Explicit spec rule. Mirrors the consolidation invariant preserved by subphase 3.30.3.

### 9. Response builder is deterministic and catalog-free
`build_modificar_producto_response(db, session, intent) -> CustomerResponse` renders:
- `pending_resolution` source: `¿Cuál producto querés cambiar: <a> o <b>( o <c>)?` from formatted `producto_nombre (presentacion_codigo)` pairs.
- `pending_resolution` destination: `¿Cuál querés como reemplazo: <a>, <b> o <c>?` from formatted `producto_nombre (presentacion_codigo)` pairs.
- `executed` full-line: `Cambié <origen> por <destino>.`
- `executed` partial: `Cambié <cantidad_modificada> <origen> por <cantidad_modificada> de <destino>. Quedan <cantidad_origen_restante> <origen>.`
- `executed` consolidated: `Cambié <cantidad_origen> <origen> por grandes. Ahora tenés <cantidad_destino_final> <destino>.`
- `rejected` excess: `Solo tenés <cantidad_origen> <origen> para cambiar.`
- `rejected` source absent: `Ese producto no está en tu pedido.`
- `rejected` destination unavailable: `Ese producto no está disponible como reemplazo.`
- `rejected` equivalent: `Ese producto ya tiene esa presentación en tu pedido.`
- `failed`: generic retry message without technical details.

`CustomerResponse.intent == "modificar_producto"` and `CustomerResponse.status == intent.status` for every outcome. No LLM call, no prompt construction, no DB IDs in the message.

**Rationale:** Mirrors the established `quitar_producto` response builder template. Keeps customer-facing messages deterministic and locale-stable.

### 10. Pending-context lifecycle preserved
- `executed` → clear pending context.
- definitive returned `rejected` → clear pending context so the next message reaches initial classification.
- raised technical exception → propagate so the transactional wrapper rolls back; do not falsely clear committed state.
- unresolved / refined → persist updated pending context with reduced candidates, current `stage`, and preserved `cantidad`.

**Rationale:** Preserves the corrected lifecycle already enforced for `agregar_producto` and `quitar_producto`. Prevents stuck pending contexts.

### 11. Hand-off: add the dispatch arms, do not copy the pipeline
The `InitialIntentDispatcher` gains one new arm: when `intent == "modificar_producto"`, it returns `ready` (when both domains resolve uniquely), `pending_resolution`, or deterministic `rejected` by calling `process_initial_modificar_producto`. The `PendingContextDispatcher` gains one new arm: when `context_type == PRODUCT_MODIFICATION`, it dispatches to `resolve_product_modification` and delegates `ready` to `execute_ready_pending_context`. The `PendingContextExecution` gains one new arm: when `handler == "modificar_producto"`, it calls `execute_modificar_producto`. The `CustomerResponseOrchestrator` gains one new arm: when `intent == "modificar_producto"`, it calls `build_modificar_producto_response`.

**Rationale:** Mirrors the established `agregar_producto` and `quitar_producto` integration pattern. Keeps each new function small and aligned with the single-responsibility rule.

### 12. Regression is a test, not a refactor
The end-to-end tests for `agregar_producto` (3.19) and `quitar_producto` (3.31) are preserved unchanged. The new test suite adds a parallel end-to-end test for `modificar_producto` plus targeted scenarios for full / partial / omitted / excess / absent / unavailable / equivalent / consolidation / new-line creation / both-ambiguous / partial-refinement / invalid-source / invalid-destination / definitive-rejection-clears / technical-exception-rolls-back / regression-against-add / regression-against-remove / mixed-operations.

**Rationale:** Avoids a broad refactor of the existing pipeline (explicit constraint in the project spec).

## Risks / Trade-offs

- **Domain confusion in the resolver** → Distinct fields (`source_candidate_ids`, `destination_candidate_ids`) and an explicit `stage` field (`source_selection` / `destination_selection`); tests assert domain identity at every transition.
- **Quantity-edge mismatch (LLM emits 0 or negative)** → Service-side check raises `PedidoProductoNotEditable` (already maps to `rejected`); the handler treats it as `rejected` with the deterministic message and never calls mutation paths with `cantidad <= 0`.
- **Race between two concurrent `modificar_producto` requests on the same Pedido** → The existing transactional processor (3.26) wraps each request in its own transaction; later writes to the same `pedido_producto_id` will surface as `PedidoProductoNotFound` (deletion) or zero current-cantidad (decrement) and be translated to `rejected` deterministically. No additional locking is introduced in this subphase.
- **Equivalent source and destination accepted by accident** → Pre-mutation check in the service compares `source.producto_presentacion_id` to `destination.producto_presentacion_id`; equality returns `rejected` with the deterministic message before any write.
- **Destination line creation bypassing the unique invariant** → Destination update reuses `add_or_increment` (consolidation required), so a destination line that already exists for the same `producto_presentacion_id` is incremented in place; never two parallel rows.
- **Customer-facing message drift across locales** → Response builder is a single deterministic Python function with no LLM involvement. Locale handling is out of scope (consistent with `agregar_producto` and `quitar_producto`).
- **Price snapshot drift** → Existing-line reuse preserves the stored snapshot; new-line creation reads the current active `Precio` row through the existing product-query service; the source line price is never modified.
- **Inheritance of `PRODUCT_SELECTION` or `ORDER_LINE_SELECTION` accidentally triggered for `modificar_producto`** → The new `ContextType` value and the resolver arm are strictly separated. The `ContextTypeResolver` returns `PRODUCT_MODIFICATION` only when the active intent is `modificar_producto`; the pending-context dispatcher dispatches by `context_type`, not by intent name.

## Migration Plan

No DB migration is required. The change is source-only and is rolled out by deploying the new Python modules alongside the existing ones.

Rollback is achieved by reverting the four dispatch arms added to `InitialIntentDispatcher`, `PendingContextDispatcher`, `PendingContextExecution`, and `CustomerResponseOrchestrator`, and by removing the new `MODIFICAR_PRODUCTO_CONTRACT` entry from the contract registry. After rollback, `modificar_producto` reverts to its current behavior (rejected by the initial dispatcher), matching today's production behavior. No data needs to be migrated or backfilled.

## Open Questions

None. The active subphase spec leaves identifier domains, quantity semantics, context structure, response strings, integration seams, and regression scope fully specified. Implementation only needs to honor them.
