## Why

Subphase 3.32 wired `modificar_producto` end-to-end through the same dispatch arms as `agregar_producto` and `quitar_producto`, but real CLI testing surfaced two defects that violate the atomic quantity-preserving contract for a modification:

1. **Source quantity is lost when destination quantity is omitted.** Sending `cambia las empanadas de verdura por empanadas carne picante` against a Pedido that contains 4 Empanadas de Verdura currently removes all 4 source units but only adds 1 Empanada de Carne Picante. The destination quantity must equal the transferred source quantity.
2. **Source is mutated before destination validation.** Sending `cambia las 5 empanadas de jamon y queso por un caramelo` against a Pedido that contains 5 Empanadas de Jamón y Queso (where `caramelo` is not in the commerce catalog) currently removes the source line and leaves the Pedido empty. The modification must be one atomic business operation: any failed destination validation must leave the Pedido exactly as it was before the message.

Both defects violate the atomic quantity-preserving contract. This change corrects them so `modificar_producto` operates as a single atomic business operation: validate source → validate quantity → validate destination → validate price and availability → calculate complete mutation → decrement or delete source → create or increment destination → one transaction commit.

## What Changes

- Enforce the authoritative quantity rule inside `PedidoProductoService.modify_product`: when the user does not provide a quantity, the full current source-line quantity is transferred to the destination; the destination quantity SHALL never default to 1.
- Enforce validation-before-mutation: every destination validation (recognition, candidate validity, active state, availability, commerce ownership, price availability, duplicate/consolidation lookup, source/destination equivalence, quantity) must complete before any source row is mutated. No commit may occur between source removal and destination addition.
- Keep `execute_modificar_producto` as the sole handler entry point that delegates to a single atomic service call. It must never call `execute_quitar_producto` or `execute_agregar_producto`, never manually decrement or create rows, and never commit or rollback.
- Preserve the destination line's stored price snapshot when the destination PedidoProducto already exists; create a new line with the current destination price snapshot otherwise. The source price must remain unchanged after a partial decrement and must never be looked up after the source has been mutated.
- Keep the existing outer transactional processor (`process_incoming_message_transactional`) as the only commit/rollback owner. The service and repositories must remain commit-free, rollback-free, and flush-free inside the modify path; existing rules for `add_or_increment` and `delete` remain intact.
- Keep the existing corrected pending-context lifecycle: definitive `rejected` clears the pending context, `executed` clears it, `failed` preserves it, raised exceptions propagate for rollback.
- Emit exactly one `ProcessedIntent` and exactly one `CustomerResponse` per modification message — never a remove response followed by an add response.
- Reuse the existing deterministic response builder, expanding the rendered messages so omitted-quantity, unknown-destination, and excess-quantity scenarios each produce a single concise customer-facing message confirming the Pedido is unchanged when applicable.
- Add focused, end-to-end, and regression automated tests covering the two real defects and the rest of the atomic-quantity matrix (omitted transfer, explicit partial, explicit full, unknown destination, unavailable destination, ambiguous destination, destination clarification after omitted quantity, destination clarification after explicit quantity, destination already exists, destination equals source, excess quantity, missing destination price for new line, technical exception before and during mutation, single `ProcessedIntent` invariant, single `CustomerResponse` invariant, HTTP regression for both defects, CLI order-table regression, `agregar_producto`/`quitar_producto`/transaction-processor regressions).
- No DB migration, no new HTTP endpoint, no CLI redesign, no LLM beautification, no extra confirmation turn, no new intent, no broad transaction changes, no lower-level commits.

## Capabilities

### New Capabilities

- `modificar-producto-atomicity-quantity`: Authoritative atomic quantity-preserving contract for `modificar_producto`: one service operation, validation-before-mutation, quantity-transfer semantics, single `ProcessedIntent` / single `CustomerResponse` invariants, and the deterministic response matrix for omitted quantity, unknown destination, and excess quantity.

### Modified Capabilities

- `modificar-producto-handler`: Strengthen the existing atomic-mutation and service-delegation requirements so the handler never decomposes the operation into separate source and destination steps, never defaults destination quantity to 1, and never mutates the source before every destination validation passes. Codify the single `ProcessedIntent` / single `CustomerResponse` invariants and the response-builder message changes.
- `modificar-producto-customer-response`: Extend the deterministic message matrix to cover the corrected outcomes — full omitted-quantity transfer, partial explicit-quantity transfer, consolidated destination increment, unknown destination (Pedido unchanged), unavailable destination (Pedido unchanged), excess quantity (Pedido unchanged) — without exposing technical details or DB IDs.
- `modificar-producto-intent-orchestration`: Strengthen the initial-orchestration and pending-context rules so destination ambiguity preserves the source ID, the original source quantity, and the omitted-quantity semantics across turns, never mutates the source, and never converts omitted quantity to 1 during refinement.

## Impact

- `backend/services/pedido_producto_service.py` — `modify_product` enforces validation-before-mutation and authoritative quantity derivation; no `commit`, `rollback`, `flush`, `refresh`, `expire`, or `begin` calls inside the modify path.
- `backend/repositories/pedido_producto_repository.py` — `decrement`, `increment`, `delete`, and `create_with_price_snapshot` continue to perform only the staged ORM change they advertise; no new public method is introduced unless strictly required.
- `backend/intents/handlers/modificar_producto_handler.py` — `execute_modificar_producto` continues to delegate to one service call and never calls `execute_quitar_producto` or `execute_agregar_producto`; never mutates rows manually; never commits or rolls back; translates the service result into one `ProcessedIntent`.
- `backend/intents/orchestration/modificar_producto_initial.py` — `process_initial_modificar_producto` keeps the existing pending-context stages and never broadens the candidate set, never converts omitted quantity to 1, and never mutates the source before the destination is ready.
- `backend/intents/orchestration/incoming_message_response_orchestrator.py` — keeps the dispatch arm to the deterministic response builder; one response per modification.
- `backend/intents/responses/modificar_producto_response.py` — extends the deterministic message matrix; no LLM call, no prompt construction, no DB ID exposure.
- `backend/intents/contracts/modificar_producto.py` — `MODIFICAR_PRODUCTO_CONTRACT` keeps the same top-level shape; no change to requirements unless a new optional field is strictly required to preserve the omitted-quantity semantics.
- `backend/tests/test_modificar_producto_end_to_end.py` and focused test files — new and updated automated tests covering the two real defects and the full atomic-quantity matrix; existing `agregar_producto`, `quitar_producto`, and transaction regressions remain green.
- `backend/scripts/cli_chat_client.py` and `backend/tests/test_cli_chat_client.py` — CLI regression covers the corrected CLI table rendering after both defect scenarios; no CLI redesign.
- No DB schema change, no Alembic migration, no Twilio, no WhatsApp adapter, no WebSocket, no HTML, no new intent.