## Why

The initial `agregar_producto` orchestration now produces ready `ProcessedIntent` values, but no handler consumes them to create the corresponding order line. Subphase 3.16 adds the first business-action handler while preserving the existing service-owned rules, transaction boundaries, and pending-context lifecycle responsibilities.

## What Changes

- Add `execute_agregar_producto(db, conversation_session, intent) -> ProcessedIntent`.
- Validate intent identity, ready status, handler name, and resolved product/quantity values.
- Resolve the session's associated draft pedido through existing application services.
- Create one `PedidoProducto` through `PedidoProductoService`, allowing the service to snapshot the current price.
- Return a copied intent with `status == "executed"` on success.
- Return a copied intent with `status == "rejected"` for expected invalid or business-rule failures and preserve original data.
- Keep context cleanup, queue promotion, response generation, and dispatch out of scope.

## Capabilities

### New Capabilities
- `agregar-producto-handler`: Defines the handler contract, validation, service delegation, execution result, and failure boundaries.

### Modified Capabilities

## Impact

- `backend/intents/handlers/agregar_producto_handler.py`
- Existing `PedidoProductoService`, pedido/session models, schemas, repositories, and exceptions
- Handler tests in `backend/tests/api_smoke.py`
- No router, migration, dependency, recognizer, contract, or generic handler abstraction changes.
