## 1. Test Fixtures and Helper

- [x] 1.1 Inspect existing `supernova_test` seeding helpers and minimal setup needed for commerce, client, session, pedido, product, presentations, and prices.
- [x] 1.2 Add or reuse a helper that creates the fixture set in a way that does not conflict with existing tests.

## 2. Integration Tests

- [x] 2.1 Add the happy-path integration test that asserts pending context after `process_initial_agregar_producto` and executed order line after `dispatch_pending_context`.
- [x] 2.2 Add the additional ambiguous-reply test that preserves pending context and creates no `PedidoProducto`.
- [x] 2.3 Run the integration tests against `supernova_test` and report results.
- [x] 2.4 Run `PYTHONPATH=. venv/bin/python -m compileall backend`.

