## 1. Handler Implementation

- [x] 1.1 Inspect `PedidoProductoService`, schemas, repositories, exceptions, and conversation-session/pedido relationships.
- [x] 1.2 Create `backend/intents/handlers/agregar_producto_handler.py` with the aliased `DatabaseSession` and `ConversationSession` typing imports and the requested function signature.
- [x] 1.3 Validate intent identity, ready status, handler name, resolved product-presentation ID, quantity, and associated pedido before service invocation.
- [x] 1.4 Delegate line creation to `PedidoProductoService` with pedido ID, presentation ID, and quantity only; do not duplicate SQLAlchemy or business rules.
- [x] 1.5 Return copied intents with `executed`, `rejected`, or `failed` status as specified while preserving original fields and pending context state.
- [x] 1.6 Keep the handler free of routers, HTTP concerns, direct repository/SQLAlchemy access, cleanup, queue promotion, and response generation.

## 2. Verification

- [x] 2.1 Add minimum ready-intent integration test creating one `PedidoProducto` with the correct pedido, presentation, quantity, and service-sourced price.
- [x] 2.2 Add rejection tests for missing/invalid product ID or quantity, non-ready/wrong intent or handler, missing pedido, and non-draft pedido.
- [x] 2.3 Add tests proving successful execution returns `executed`, preserves fields, and does not clear pending context or context type.
- [x] 2.4 Add source/behavior checks proving no direct SQLAlchemy query, repository, router, or HTTP exception usage.
- [x] 2.5 Run the minimum relevant handler tests against `supernova_test`.
- [x] 2.6 Run `PYTHONPATH=. venv/bin/python -m compileall backend`.
