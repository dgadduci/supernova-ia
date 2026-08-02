## Why

Phase 3 introduces the "intents" layer that the WhatsApp channel will dispatch through. Each intent is a typed contract that ties a recognizer (the LLM-based NLP step) to a handler (the eventual state-mutating step) and declares the parameters it needs. Without an `agregar_producto` contract the system has no vocabulary for the "add a product to the current pedido" interaction that the WhatsApp channel needs to expose to customers.

## What Changes

- Add `backend/intents/__init__.py` and `backend/intents/contracts/__init__.py` (empty package markers).
- Add `backend/intents/contracts/agregar_producto.py` exporting a single constant `AGREGAR_PRODUCTO_CONTRACT`.
- The contract is a static Python dictionary with four keys: `intent`, `recognizer`, `handler`, and `requirements`. The `requirements` value is itself a dictionary keyed by requirement name; each requirement declares `required: bool` and `default: ...`.
- Add one integration test that imports the contract and asserts the keys, types, and values match the spec.

## Capabilities

### New Capabilities

- `agregar-producto-contract`: The static contract that the WhatsApp channel uses to dispatch the "agregar_producto" intent to the `agregar_producto` handler via the `recognizer_productos` recognizer.

### Modified Capabilities

- None.

## Impact

- Adds `backend/intents/__init__.py`, `backend/intents/contracts/__init__.py`, `backend/intents/contracts/agregar_producto.py`.
- Adds one test entry to `backend/tests/api_smoke.py` (or a new test file under `backend/tests/`).
- No model, no migration, no router, no service code. The contract is pure data.
- No new runtime dependencies.