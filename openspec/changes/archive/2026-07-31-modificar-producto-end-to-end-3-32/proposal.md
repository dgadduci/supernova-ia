## Why

The modern message-processing pipeline now supports `agregar_producto` and `quitar_producto` end-to-end (subphases 3.19 and 3.31), but `modificar_producto` — replacing all or part of one existing `PedidoProducto` line with another producto-presentación — still has no contract, no recognizer, no resolver, no handler, and no response builder. Customers cannot mutate the lines they already added through the conversational pipeline even though `modificar_producto` is an established `IntentName` and the legacy classifier returns it today.

This change closes that gap by implementing the complete `modificar_producto` flow through the same architectural seams used for `agregar_producto` and `quitar_producto`: static contract → source/destination recognition → `product_modification` context with explicit `source_selection` and `destination_selection` stages → initial intent dispatcher → pending-context dispatcher → ready handler → deterministic customer response → HTTP and CLI integration. It mutates only `PedidoProducto` rows of the active draft Pedido, never the catalog, and preserves the unique order-line invariant already enforced today.

## What Changes

- Add a new static `MODIFICAR_PRODUCTO_CONTRACT` alongside the existing `AGREGAR_PRODUCTO_CONTRACT` and `QUITAR_PRODUCTO_CONTRACT`, exposing `pedido_producto_origen_id` (required, default `None`) and `producto_presentacion_destino_id` (required, default `None`), plus optional `cantidad` (default `None`).
- Add a recognizer adapter that emits one or more source candidates drawn exclusively from the active draft Pedido's `PedidoProducto` lines and one or more destination candidates drawn from the comercio's active and available catalog, preserving an optional explicit quantity.
- Add an initial `modificar_producto` orchestration function (`process_initial_modificar_producto`) that resolves both domains, returns `ready` when both resolve uniquely, returns `pending_resolution` when either remains ambiguous, and returns deterministic `rejected` when the source is absent, the destination is unavailable, or the source equals the destination.
- Introduce the smallest dedicated context type (`PRODUCT_MODIFICATION`) with explicit `source_selection` and `destination_selection` stages so the source domain (PedidoProducto IDs) and the destination domain (producto_presentacion IDs) never share one overloaded `candidate_ids` list.
- Add a pending-context resolver that refines source candidates first, then destination candidates, never broadening back to the full Pedido or full catalog.
- Add an atomic service operation (`modify_product`) that decrements or deletes the source line, then creates or increments the destination line, preserving the unique `(pedido_id, producto_presentacion_id)` invariant and reusing existing price snapshots.
- Add a handler (`execute_modificar_producto`) that validates the resolved intent and delegates the atomic mutation to the service layer.
- Add a deterministic response builder for `modificar_producto` covering source pending, destination pending, full-line executed, partial executed, consolidated executed, excess quantity, source absent, destination unavailable, source equals destination, and generic failed outcomes.
- Wire `modificar_producto` into the intent contract registry, initial intent dispatcher, pending-context dispatcher, ready-handler execution, customer-response orchestrator, and the existing transactional incoming-message flow.
- No new HTTP endpoint, no CLI change, no LLM beautification, no extra confirmation turn, no DB migration, no `vaciar_pedido`, no `consultar_estado`.

## Capabilities

### New Capabilities

- `modificar-producto-contract`: Static `MODIFICAR_PRODUCTO_CONTRACT` dict literal in `backend/intents/contracts/modificar_producto.py` declaring `pedido_producto_origen_id`, `producto_presentacion_destino_id`, and optional `cantidad`.
- `modificar-producto-recognizer`: Recognizer adapter that detects source candidates among current `PedidoProducto` lines of the active draft Pedido and destination candidates among active and available catalog producto-presentaciones of the same comercio, plus an optional positive integer quantity.
- `modificar-producto-intent-orchestration`: `process_initial_modificar_producto` plus the new `PRODUCT_MODIFICATION` context type, `source_selection` / `destination_selection` stages, and the refinement resolver used to disambiguate across turns.
- `modificar-producto-handler`: `execute_modificar_producto` plus the atomic `modify_product` service operation that decrements or deletes the source line and creates or increments the destination line.
- `modificar-producto-customer-response`: Deterministic response builder covering source pending, destination pending, executed (full, partial, consolidated), rejected (excess, source absent, destination unavailable, source equals destination), and failed outcomes.

### Modified Capabilities

- `initial-intent-dispatcher`: Must recognize `modificar_producto` as a supported initial intent and route to `process_initial_modificar_producto` instead of rejecting it.
- `pending-context-dispatcher`: Must route an active `PRODUCT_MODIFICATION` context to the new refinement path, persisting the active intent and delegating `ready` to the existing ready-execution path.
- `pending-context-execution`: Must dispatch `handler == "modificar_producto"` to `execute_modificar_producto` while preserving the existing `agregar_producto` and `quitar_producto` arms and the rejection-clears-context rule.
- `incoming-message-response-orchestrator`: Must dispatch `executed` / `pending_resolution` / `rejected` / `failed` `modificar_producto` outcomes to the new deterministic response builder instead of the generic fallback.
- `product-selection-context-resolver`, `product-selection-context-orchestration`, `order-line-selection-resolver`, `intent-classifier`, `intent-classification-contracts`, `incoming-message-orchestrator`, `incoming-message-transactional-processor`, `incoming-message-response-orchestrator`, `incoming-messages-local-http-endpoint`, `incoming-messages-interactive-cli`: regression scope only — no spec-level requirement changes, but their existing rules and lifecycles must remain intact after this change is wired in.

## Impact

- New modules under `backend/intents/contracts/`, `backend/intents/recognizers/`, `backend/intents/orchestration/`, `backend/intents/handlers/`, `backend/intents/responses/`, and `backend/intents/context/` for the modification context and resolver.
- `PedidoProductoService` gains the minimum surface required for atomic modification (line lookup, decrement, delete, increment, create with current price snapshot); `PedidoProductoRepository` gains the matching DB-only operations.
- `ContextType` enum grows by one value (`PRODUCT_MODIFICATION`); pending-context dispatch grows by one route; the modification context carries an explicit `stage` field (`source_selection` or `destination_selection`).
- `CustomerResponseOrchestrator`, `InitialIntentDispatcher`, `PendingContextDispatcher`, and `PendingContextExecution` gain new dispatch arms.
- HTTP endpoint `POST /comercios/{id}/clientes/{id}/incoming-messages` and the interactive CLI are unchanged; the CLI must drive `modificar_producto` through the existing HTTP contract.
- No DB schema changes; no Alembic migration.
- `agregar_producto` and `quitar_producto` flows are unchanged; both remain covered by their existing regression tests.
