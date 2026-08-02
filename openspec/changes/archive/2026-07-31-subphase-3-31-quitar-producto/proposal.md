## Why

The modern message-processing pipeline currently supports only `agregar_producto` end-to-end. Customers cannot remove items already added to the active draft Pedido through the same pipeline, even though `quitar_producto` is an established `IntentName` (legacy classifier, subphase 3.20) and the candidate-resolution contract already covers it (subphase 3.23/3.25).

This change closes that gap by implementing the complete `quitar_producto` flow through the same architecture as `agregar_producto`: classification → order-line recognition → candidate resolution when needed → handler execution → persistence → deterministic customer response → HTTP/CLI integration. It targets the active draft Pedido, mutates existing `PedidoProducto` rows (decrement or delete), and never modifies the catalog. The result lets the existing interactive CLI test removal through one or several consecutive messages without changing the HTTP endpoint.

## What Changes

- Add a new static `QUITAR_PRODUCTO_CONTRACT` alongside `AGREGAR_PRODUCTO_CONTRACT`, exposing `pedido_producto_id` (required, default `None`) and `cantidad` (optional, default `None`).
- Add a recognizer adapter that takes the active draft Pedido's current `PedidoProducto` lines and emits one or more `pedido_producto_id` candidates together with an optional `cantidad`.
- Add an initial `quitar_producto` orchestration function (`process_initial_quitar_producto`) that resolves a unique line, returns `pending_resolution` for ambiguous matches, or returns a definitive `rejected` / `unresolved` outcome when no line matches.
- Reuse the existing pending-context dispatcher and add the smallest dedicated context type (`ORDER_LINE_SELECTION`) so that ambiguous matches refine the candidate set across turns without broadening it back to the full catalog and without breaking `PRODUCT_SELECTION`.
- Add a handler (`execute_quitar_producto`) that validates the resolved `pedido_producto_id`, enforces non-positive and excess-quantity rules, then either decrements or deletes the `PedidoProducto` row.
- Add the minimum repository and service operations required to list current order lines for a draft Pedido, fetch a specific line, decrement its quantity, and delete it. Service owns draft-state and ownership checks; repository is DB-only.
- Add a deterministic response builder for `quitar_producto` covering `pending_resolution`, `executed` (partial removal), `executed` (complete line removal), `rejected` (excess quantity), `rejected` (not in pedido), and `failed`.
- Wire `quitar_producto` into initial intent dispatch, pending-context dispatch, ready-handler execution, and the customer-response orchestrator.
- No new HTTP endpoint, no CLI changes, no LLM beautification, no migration, no `modificar_producto`, no other intents.

## Capabilities

### New Capabilities

- `quitar-producto-contract`: Static `QUITAR_PRODUCTO_CONTRACT` dict literal in `backend/intents/contracts/quitar_producto.py`.
- `quitar-producto-recognizer`: Recognizer adapter that detects an existing `PedidoProducto` line from the draft Pedido's catalog and an optional quantity.
- `quitar-producto-intent-orchestration`: `process_initial_quitar_producto` and the `ORDER_LINE_SELECTION` context type plus resolver used for ambiguous refinement.
- `quitar-producto-handler`: `execute_quitar_producto` plus the minimum `PedidoProducto` repository/service operations (list, get, decrement, delete).
- `quitar-producto-customer-response`: Deterministic response builder covering `pending_resolution`, `executed`, `rejected`, and `failed` outcomes.
- `quitar-producto-end-to-end`: Integration of the full `quitar_producto` flow into initial intent dispatch, pending-context dispatch, ready-handler execution, the customer-response orchestrator, and the existing transactional incoming-message flow.

### Modified Capabilities

- `initial-intent-dispatcher`: Must recognize `quitar_producto` as a supported initial intent and route to `process_initial_quitar_producto` instead of rejecting it.
- `pending-context-dispatcher`: Must route an active `ORDER_LINE_SELECTION` context to the new order-line refinement path without broadening candidates.
- `pending-context-execution`: Must clear the pending context after a definitive `rejected` outcome from the `quitar_producto` handler so the session is not stuck.
- `incoming-message-response-orchestrator`: Must dispatch `executed` / `pending_resolution` / `rejected` / `failed` `quitar_producto` outcomes to the new deterministic response builder instead of the generic fallback.
- `intent-classification-contracts`: Static classifier contract list must already include `quitar_producto` (it does today); no new requirements added, but the runtime intent dispatcher now actually accepts it.

## Impact

- New modules under `backend/intents/contracts/`, `backend/intents/recognizers/`, `backend/intents/orchestration/`, `backend/intents/handlers/`, `backend/intents/responses/`, and the `backend/intents/context/` package.
- `PedidoProductoService` gains `list_by_pedido`, `get_for_pedido`, `decrement_quantity`, and `delete` methods; `PedidoProductoRepository` gains the matching DB-only operations.
- `ContextType` enum grows by one value (`ORDER_LINE_SELECTION`); pending-context dispatch grows by one route.
- `CustomerResponseOrchestrator` and `InitialIntentDispatcher` grow new dispatch arms.
- HTTP endpoint `POST /comercios/{id}/clientes/{id}/incoming-messages` and the interactive CLI are unchanged.
- No DB schema changes; no Alembic migration.
- `agregar_producto` flow is unchanged; covered by a regression test.
