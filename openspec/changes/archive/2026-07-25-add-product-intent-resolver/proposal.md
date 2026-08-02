## Why

Subphase 3.3 introduced `ProcessedIntent` with `resolved_data: dict[str, Any]` and `candidate_ids: list[int]`. The future recognizer `recognizer_productos` is an LLM-based step that returns its findings in a recognizer-specific shape: items it is confident about (`encontrados`), items it is unsure about (`encontrados_posibles`), items that exist but are unavailable right now (`encontrados_no_disponibles`), and items the user mentioned that the recognizer could not match at all (`no_encontrados`). Without a typed translation from the recognizer's shape to the `ProcessedIntent` shape, every future recognizer adapter has to reimplement that translation — and the rules around how to handle each group are easy to get wrong. A single dedicated resolver is the canonical adapter.

## What Changes

- Add `backend/intents/__init__.py` already exists (subphase 3.1) and `backend/intents/resolvers/__init__.py` (new package marker).
- Add `backend/intents/resolvers/product_intent_resolver.py` exporting a single function `resolve_product_intent(raw: dict) -> dict` (signature to be decided in the design phase; the spec mandates a Python function).
- The function takes a `dict` with keys `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados` and returns a `dict` with keys `resolved_data`, `candidate_ids`, `unavailable_items`, `not_found_items`.
- Add one test entry to `backend/tests/api_smoke.py` covering: exact product found, multiple possible candidates, unavailable products, not-found products, and empty recognizer result.

## Capabilities

### New Capabilities

- `product-intent-resolver`: The pure function that translates the recognizer's `recognizer_productos` output shape into the `ProcessedIntent` runtime shape. This is the smallest, narrowest piece of the recognizer path that has well-defined input/output contract.

### Modified Capabilities

- None.

## Impact

- Adds `backend/intents/resolvers/__init__.py` and `backend/intents/resolvers/product_intent_resolver.py`.
- Adds one test entry to `backend/tests/api_smoke.py`.
- No model, no migration, no router, no FastAPI endpoint, no DB write, no LLM call, no intent contract application, no handler execution, no persistence. The function is pure.
- No new runtime dependencies.