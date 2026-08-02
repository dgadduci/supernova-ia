## Why

The pending-context dispatcher now completes the agregar_producto lifecycle, but there is no single integration test that proves the full two-message flow against real components and `supernova_test`. Subphase 3.19 adds an end-to-end integration test that locks the behavior without introducing new production code.

## What Changes

- Add one integration test in `backend/tests/api_smoke.py` that exercises the full pending-context flow against real models, recognizer, resolver, processor, dispatcher, handler, and services.
- Cover the happy path through pending selection to executed order line plus one additional ambiguous-reply test.
- Keep fixtures and helpers minimal.
- Run only against `supernova_test` and avoid mocks on the main flow.

## Capabilities

### New Capabilities

### Modified Capabilities

## Impact

- `backend/tests/api_smoke.py`
- Reuse of existing product, client, session, pedido, presentation, and price models/services
- No production code, recognizer, resolver, processor, dispatcher, handler, contract, router, migration, dependency, or generic intent classifier changes.
