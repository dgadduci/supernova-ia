## Context

The Phase 3 intent pipeline already wires `agregar_producto` end-to-end through: static contract (3.1) → recognizer adapter (3.11/3.25) → `product_selection` context resolver (3.12/3.14) → initial intent dispatcher (3.15) → ready handler (3.16) → pending-context dispatcher (3.18) → close pending context (3.17) → end-to-end test (3.19) → contracts (3.20) → intent classifier (3.22) → classifier integration (3.23) → incoming-message orchestrator (3.24) → incoming-message integration (3.25) → transactional processor (3.26) → customer-response orchestrator (3.28) → local HTTP endpoint (3.29) → interactive CLI (3.30) → CLI defect fixes (3.30.1).

`quitar_producto` is an established `IntentName` (3.20), the classifier already returns it (3.22/3.23), and the local HTTP endpoint plus interactive CLI (3.29/3.30) accept it. The classifier-integration tests (3.25) confirm `quitar_producto` currently produces a `ProcessedIntent` with `status="rejected"` and `handler="quitar_producto"` because the dispatcher does not know the intent. There is no contract, no recognizer, no resolver, no handler, and no response builder for it.

The active draft Pedido holds one `PedidoProducto` row per `producto_presentacion_id` (one-to-one unique index on `pedidos_productos.id_producto_presentacion` per pedido, enforced by the existing subphase 2.14 endpoint behavior). Adding the same presentation consolidates the quantity into one row. The `PedidoProductoService` already exposes `update` (cantidad/observaciones) and `delete`; both enforce the borrador-only guard and return `PedidoProductoNotEditable` / `PedidoProductoNotFound`. The Pedido has an `id_session` back-reference that already flows through `Session.id_pedido`.

`SESSION_CONTEXT_TYPE` (subphase 3.8) has exactly one value today (`PRODUCT_SELECTION`); the active `ContextType` resolver (3.9) is the only route the pending-context dispatcher (3.18) consults. Adding a second value requires a new dedicated resolver because the existing `PRODUCT_SELECTION` resolver matches catalog `producto_presentacion_id`s, not `pedido_producto_id`s, and broadening it would corrupt `agregar_producto` (rule explicitly preserved).

## Goals / Non-Goals

**Goals:**
- Make `quitar_producto` executable end-to-end through the same architectural seams as `agregar_producto`: initial intent dispatcher → orchestration → pending-context dispatcher → handler → customer-response orchestrator.
- Mutate only `PedidoProducto` rows that already exist in the active draft Pedido. Never reach into the catalog.
- Resolve the order line by `pedido_producto_id` once recognized. Catalog-wide `producto_presentacion_id` is never a final mutation target when the order line is ambiguous.
- Support partial removal (decrement), exact removal (delete), and explicit quantity rejection when the requested quantity exceeds the line's current quantity.
- Support multi-turn refinement of ambiguous matches with the smallest dedicated context type and resolver.
- Produce deterministic customer responses without LLM beautification.
- Reuse the existing transactional incoming-message flow and the existing CLI without changes.

**Non-Goals:**
- No `modificar_producto`, no quantity adjustment other than decrement-to-removal, no observations edit.
- No new HTTP endpoint, no CLI change.
- No DB schema change, no Alembic migration.
- No LLM-driven response generation.
- No Pedido-level removal (`vaciar_pedido`), no catalog deactivation.
- No Twilio, no WhatsApp adapter, no extra confirmation turn.

## Decisions

### 1. Identifier semantics: `pedido_producto_id`, not `producto_presentacion_id`
`PedidoProducto` already uses a unique index on `id_producto_presentacion` per pedido (the same `id_pedido`, `id_producto_presentacion` pair cannot coexist). However, the recognizer is given the active draft's `PedidoProducto` lines and may emit multiple candidates. The resolved intent must carry `pedido_producto_id` so the handler operates on the specific order line.

**Rationale:** `producto_presentacion_id` is a catalog key. Once an order has multiple presentations of the same product (different presentations, same producto), or duplicates by re-add, the order line is the only stable target.

### 2. New `ContextType` value: `ORDER_LINE_SELECTION`
A new enum value `ORDER_LINE_SELECTION` is added to `SESSION_CONTEXT_TYPE`. It carries `pedido_producto_id` candidates and is exclusively used for `quitar_producto` refinement.

**Rationale:** The existing `PRODUCT_SELECTION` resolver validates against catalog `producto_presentacion_id` and would corrupt `agregar_producto` if reused. A dedicated context type and resolver keeps the two flows strictly isolated.

### 3. Recognizer scope: only current order lines
The recognizer for `quitar_producto` receives a catalog built from the active draft Pedido's current `PedidoProducto` lines. Each catalog entry includes `pedido_producto_id`, `producto_presentacion_id`, product name, presentation code/description, and current `cantidad`. Catalog products absent from the pedido are unreachable.

**Rationale:** Aligns with the business rule "products not present in the draft Pedido must not appear as valid candidates" (spec rule 2). Reusing `detectar_productos` would require a different product-to-id mapping and would risk broadening scope.

### 4. Handler delegates to `PedidoProductoService` (existing module)
The new `execute_quitar_producto` calls into `PedidoProductoService` after validating the ready intent. Two cases:
- `cantidad >= current.cantidad` → `service.delete(pedido_producto_id)`.
- `cantidad < current.cantidad` → `service.update(pedido_producto_id, cantidad=current.cantidad - cantidad)`.

Excess quantity (where requested `cantidad > current.cantidad` and the caller did not say "all") returns `rejected` with a deterministic message and does not mutate.

**Rationale:** The borrador-only guard and FK semantics (CASCADE on pedido, RESTRICT on presentation) already exist in `PedidoProductoService` from subphase 2.14. Reuse avoids duplicating state-machine and integrity logic.

### 5. Definitive `rejected` clears the pending context
When the handler returns `rejected` for an `ORDER_LINE_SELECTION` refinement (e.g. invalid candidate, excess quantity), the existing pending-context execution path (3.17) is responsible for clearing `pending_intents` and `context_type`. This matches the corrected lifecycle already established for `agregar_producto`.

**Rationale:** Prevents the session being trapped in a stuck state. Aligns with the rule "A returned definitive `rejected` result must not leave the session trapped in a pending or ready product-selection context."

### 6. Response builder is deterministic and catalog-free
`build_quitar_producto_response(intent: ProcessedIntent, context: QuitarProductoContext) -> str` renders:
- `pending_resolution`: "¿Cuál querés quitar: {names joined by ' o '}?" with only refined candidates.
- `executed` partial: "Quité {cantidad} {product} ({presentation}). Queda {remaining} en tu pedido."
- `executed` complete: "Quité {product} ({presentation}) de tu pedido."
- `rejected` excess: "Solo tenés {current} {product} ({presentation}) en el pedido."
- `rejected` not in pedido: "Ese producto no está en tu pedido."
- `failed`: generic retry message.

**Rationale:** The active subphase explicitly forbids LLM beautification and forbids exposing DB IDs to the customer. The orchestrator must call this builder, not the generic fallback.

### 7. Hand-off: add the dispatch arms, do not copy the pipeline
The `InitialIntentDispatcher` (3.15) gains one new arm: when `intent == "quitar_producto"`, it returns a `pending_resolution` (or `executed` if unique) by calling `process_initial_quitar_producto`. The `PendingContextDispatcher` (3.18) gains one new arm: when `context_type == ORDER_LINE_SELECTION`, it calls `resolve_order_line_selection`. The `CustomerResponseOrchestrator` (3.28) gains one new arm: when `intent == "quitar_producto"`, it calls `build_quitar_producto_response`.

**Rationale:** Mirrors the established `agregar_producto` integration pattern. Keeps each new function small and aligned with the single-responsibility rule.

### 8. Repository: list, get-for-pedido, decrement, delete
`PedidoProductoRepository` gains `list_by_pedido(db, pedido_id)`, `get_for_pedido(db, pedido_id, pedido_producto_id)`, and reuses existing `update` and `delete`. `PedidoProductoService` exposes the matching service methods with ownership/draft checks. The handler uses the service, never the repository.

**Rationale:** The service owns the borrador guard and FK rules; the repository stays DB-only.

### 9. Existing `agregar_producto` regression is a test, not a refactor
The end-to-end test for `agregar_producto` (subphase 3.19) is preserved unchanged. The new test suite adds a parallel end-to-end test for `quitar_producto` plus targeted scenarios for decrement / excess / absent / ambiguous refinement / invalid candidate / handler rejection / transaction rollback.

**Rationale:** Avoids a broad refactor of the existing pipeline (explicit constraint in the active subphase).

## Risks / Trade-offs

- **Wrong candidate acceptance by the resolver** → Re-validation against the currently refined candidate set in the resolver before returning `ready`; the handler additionally re-validates against the pedido before mutating.
- **Quantity-edge mismatch (LLM emits `0` or negative)** → Service-side check raises `PedidoProductoNotEditable` (already maps to rejected); the handler treats it as a `rejected` with a deterministic message and never calls `update` with `cantidad <= 0`.
- **Race between two concurrent `quitar_producto` requests on the same pedido** → The existing transactional processor (3.26) wraps each request in its own transaction; later writes to the same `pedido_producto_id` will surface as `PedidoProductoNotFound` (deletion) or zero current-cantidad (decrement) and be translated to `rejected` deterministically. No additional locking is introduced in this subphase.
- **Inheritance of `PRODUCT_SELECTION` accidentally triggered for `quitar_producto`** → The new `ContextType` value and the resolver arm are strictly separated. The `ContextTypeResolver` (3.9) returns `ORDER_LINE_SELECTION` only when the active intent is `quitar_producto`; the pending-context dispatcher (3.18) dispatches by `context_type`, not by intent name.
- **Customer-facing message drift across locales** → The response builder is a single deterministic Python function with no LLM involvement. Locale handling is out of scope (consistent with existing `agregar_producto` response builder).
- **Removal of a row that is still referenced by other code paths** → `PedidoProducto.id_pedido` is `ON DELETE CASCADE`, and no other table references `pedidos_productos.id` today. Deletion is safe; the handler returns the deleted flag so the response builder can phrase "removed" vs. "decremented".

## Migration Plan

No DB migration is required. The change is source-only and is rolled out by deploying the new Python modules alongside the existing ones.

Rollback is achieved by reverting the four dispatch arms added to `InitialIntentDispatcher`, `PendingContextDispatcher`, `PendingContextExecution`, and `CustomerResponseOrchestrator`. After rollback, `quitar_producto` reverts to its current behavior (rejected by the initial dispatcher), matching today's production behavior. No data needs to be migrated or backfilled.

## Open Questions

None. The active subphase spec leaves quantity semantics, identifier choice, context type, response strings, and integration seams fully specified. Implementation only needs to honor them.
