## Context

The pending-context dispatcher closes the agregar_producto lifecycle, but no single integration test exercises the entire two-message flow against real models, recognizer, resolver, processor, dispatcher, handler, and services. This subphase adds one focused test that proves the happy path and one ambiguous-reply test that locks the pending preservation path.

## Goals / Non-Goals

**Goals:**
- Cover the full agregar_producto flow with one happy-path integration test.
- Cover the ambiguous second reply path with one focused test.
- Use real services against `supernova_test` with minimal fixtures.
- Avoid mocks on the main flow components.

**Non-Goals:**
- New production code unless the test exposes a real integration defect.
- Mocking the main flow or duplicating component-level tests.
- Implementing an `intent_classifier` or other subphases.

## Decisions

- Add a single integration test that builds commerce, client, active session, draft pedido, one product with two active presentations (`chica` and `grande`), and prices for both.
- Invoke `process_initial_agregar_producto` first to assert `pending_resolution`, context type `product_selection`, active pending intent, and zero `PedidoProducto` rows.
- Invoke `dispatch_pending_context` with `la grande` to assert `executed`, exactly one `PedidoProducto` for the `grande` presentation with `cantidad == 2`, the database price, and cleared pending state.
- Add only one extra ambiguous-reply test that re-asserts `pending_resolution`, preserved context, and zero `PedidoProducto` rows.
- Reuse existing helpers for fixtures when available and add minimal helpers only when required.

## Risks / Trade-offs

- [Risk] The test could conflict with `supernova_test` state → Mitigation: use unique commerce/client/session identifiers and clean up the created rows.
- [Risk] Adding tests may surface integration defects → Mitigation: keep production code untouched unless the test exposes a real defect, and report the defect separately.

## Migration Plan

1. Inventory existing test helpers and seed data for `supernova_test`.
2. Add the happy-path integration test with minimal helpers.
3. Add the ambiguous-reply test reusing the same fixture.
4. Run the integration tests and report results.
5. Roll back by removing the tests if needed; existing components are unaffected.

## Open Questions

None.
