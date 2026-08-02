## 1. Resolver Module

- [x] 1.1 Create the empty package marker `backend/intents/resolvers/__init__.py`.
- [x] 1.2 Create `backend/intents/resolvers/product_intent_resolver.py` exporting one function:
  - `resolve_product_intent(raw: dict) -> dict` — pure, no I/O, no LLM, no DB, no intent contract, no handler.
  - The function reads four optional input keys (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`), each defaulting to `[]` when missing.
  - The function returns a dict with exactly four keys (`resolved_data`, `candidate_ids`, `unavailable_items`, `not_found_items`):
    - `resolved_data: dict[str, Any]`. If `encontrados` has at least one item, set `producto_presentacion_id` to that item's `id` and `cantidad` to that item's `cantidad`. If `encontrados` is empty and `encontrados_posibles` has at least one item with a `cantidad`, set `cantidad` from the first such item; otherwise `resolved_data` is `{}`.
    - `candidate_ids: list[int]` — every `id` from `encontrados_posibles` collected in order. Empty when `encontrados` is non-empty.
    - `unavailable_items: list[str]` — every `source_text` from `encontrados_no_disponibles` in order.
    - `not_found_items: list[str]` — every `source_text` from `no_encontrados` in order.

## 2. Verification

- [x] 2.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `resolve_product_intent`;
  - asserts single confident match populates `resolved_data` with `producto_presentacion_id` and `cantidad`;
  - asserts multiple candidates populate `candidate_ids` in order and preserve the first candidate's `cantidad` in `resolved_data`;
  - asserts a candidate without `cantidad` leaves `resolved_data == {}`;
  - asserts unavailable items are copied into `unavailable_items`;
  - asserts not-found items are copied into `not_found_items`;
  - asserts empty input produces fully empty output;
  - asserts all-empty input produces fully empty output;
  - asserts missing keys default to empty;
  - asserts confident match suppresses candidates;
  - asserts all four output keys are always present;
  - asserts the only file in the resolvers package is `product_intent_resolver.py`;
  - asserts the only public symbol defined in the module is `resolve_product_intent`.
- [x] 2.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 249 tests.
- [x] 2.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new file compiles.