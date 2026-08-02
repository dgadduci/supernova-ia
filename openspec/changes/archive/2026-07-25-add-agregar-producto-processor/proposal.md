## Why

Subphase 3.5 introduced `resolve_product_intent` — the pure function that translates the recognizer's output dict into the `resolved_data` / `candidate_ids` / `unavailable_items` / `not_found_items` shape. The runtime side of the system has nothing that consumes that shape and turns it into a `ProcessedIntent`. Without a processor, the future recognizer-adapter subphase has no canonical way to bridge "recognizer output" and the typed envelope introduced in subphase 3.3. The processor is the small, pure, well-defined function that closes that gap.

## What Changes

- Add `backend/intents/processor.py` exporting a single function `process_agregar_producto(source_text: str, normalized_result: dict) -> ProcessedIntent`.
- The function reads the contract from subphase 3.1 (`AGREGAR_PRODUCTO_CONTRACT`) to know which requirements exist, which are required, and what their defaults are.
- The function reads the resolver output from subphase 3.5 (`normalized_result`) to know which slots have values and which are missing.
- The function builds one `RequirementState` per contract requirement, marks each `completed` (if the resolver produced a value) or `pending` (otherwise), applies contract defaults, and decides the `ProcessedIntent.status` (`ready` if every required requirement is `completed`, else `pending_resolution`).
- The function is **pure** — no recognizer call, no handler call, no DB, no persistence.
- Add one test entry to `backend/tests/api_smoke.py` covering: all-required-completed returns `ready`, missing product-presentation returns `pending_resolution`, default `cantidad=1` is applied, candidate IDs are preserved, and the returned value passes Pydantic validation.

## Capabilities

### New Capabilities

- `agregar-producto-processor`: The pure function that turns the `ProductIntentResolver` output into a `ProcessedIntent` envelope for the `agregar_producto` intent. It applies the contract defaults and decides the resolution status.

### Modified Capabilities

- None.

## Impact

- Adds `backend/intents/processor.py`.
- Adds one test entry to `backend/tests/api_smoke.py`.
- No model, no migration, no router, no FastAPI endpoint, no recognizer call, no handler invocation, no DB write, no persistence. The function is pure.
- Reuses existing imports: `AGREGAR_PRODUCTO_CONTRACT` (subphase 3.1), `RequirementState` (subphase 3.2), `ProcessedIntent` (subphase 3.3).
- No new runtime dependencies.