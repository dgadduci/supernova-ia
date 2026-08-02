## Context

Phase 3 (Intents) is layering up the runtime. Subphase 3.1 (static contract), 3.2 (per-requirement state), 3.3 (per-intent envelope), 3.4 (conversation-wide state), 3.5 (recognizer → resolver adapter). The next layer is the *processor* — the function that turns the resolver output into a `ProcessedIntent`. The contract (`AGREGAR_PRODUCTO_CONTRACT`) declares the requirements; the resolver produces the per-slot values; the processor bridges the two. The processor is the first piece that touches both the contract and the envelope at once. It is pure, with no side effects, so the future recognizer-adapter subphase (and the future dispatch layer) can call it freely.

## Goals / Non-Goals

**Goals:**

- Create a single Python file `backend/intents/processor.py` exporting one function `process_agregar_producto(source_text: str, normalized_result: dict) -> ProcessedIntent`.
- The function reads `resolved_data` and `candidate_ids` from `normalized_result`.
- The function iterates the contract's `requirements`, applies the default for each missing value, and builds one `RequirementState` per requirement. A requirement is `completed` if the resolver supplied a value (key present in `resolved_data`), else `pending`.
- The function returns `ProcessedIntent.status == "ready"` when every **required** requirement is `completed`, else `"pending_resolution"`.
- The returned `ProcessedIntent` preserves `source_text`, `recognizer` (`"recognizer_productos"` from the contract), `handler` (`"agregar_producto"` from the contract), `resolved_data`, and `candidate_ids`.
- The function is **pure** — no recognizer call, no handler call, no DB, no persistence.
- One test asserts: all-required-completed returns `ready`; missing product-presentation returns `pending_resolution`; default `cantidad=1` is applied; candidate IDs are preserved; and the returned value passes Pydantic validation.

**Non-Goals:**

- No recognizer call, no HTTP, no LLM, no async. The recognizer-adapter subphase is a future concern.
- No handler invocation, no DB write, no `pedido_producto` HTTP call, no persistence. The handler subphase is a future concern.
- No mutating the input `normalized_result` (the function returns a new `ProcessedIntent`).
- No additional `IntentProcessor` (e.g. `process_cerrar_pedido`). One processor per subphase.

## Decisions

- **D1 — Function signature: `process_agregar_producto(source_text: str, normalized_result: dict) -> ProcessedIntent`.** Two positional parameters and a typed return. The function does not take a `Session` or any service object; it is pure.
- **D2 — Source of truth: `AGREGAR_PRODUCTO_CONTRACT` (subphase 3.1).** The function reads the contract at call time (the contract is a module-level `dict`). This is the only place the contract is consulted, so a future subphase that updates the contract (e.g. adds a new requirement) needs no changes here.
- **D3 — Slot lookup uses `resolved_data` keys.** A requirement with name `producto_presentacion_id` is satisfied if the key `producto_presentacion_id` is **present** in `resolved_data` (even if its value is `None` or `0`). The contract declares `default: None` for `producto_presentacion_id`, so the default value fills in only when the key is missing entirely.
- **D4 — A requirement is `completed` if the key is present in `resolved_data`, else `pending`.** The value of `resolved_data[key]` is used as the `value` of the `RequirementState` regardless of its Python type. This preserves the original (possibly `None`) value from the resolver.
- **D5 — `status == "ready"` iff every **required** requirement is `completed`.** Non-required requirements (e.g. an optional one) are ignored when computing the status. The current contract has both requirements as `required: True`, so this distinction does not affect today's behavior, but it makes the processor future-proof.
- **D6 — Defaults are applied to the `RequirementState.value` when the key is missing.** The default value comes from the contract's `default` field (e.g. `1` for `cantidad`, `None` for `producto_presentacion_id`). The key is still set on the `RequirementState`; only `status` is `pending`.
- **D7 — `recognizer` and `handler` come from the contract.** The contract declares `"recognizer": "recognizer_productos"` and `"handler": "agregar_producto"`. The processor copies them into the `ProcessedIntent` so the future dispatch layer knows where the intent came from and where to send it. The `source_text` parameter is the raw user text and is preserved on the `ProcessedIntent`.
- **D8 — `candidate_ids` is preserved verbatim.** The processor does not dedupe, sort, or filter the list. The future handler uses it to disambiguate.
- **D9 — No mutating the input.** The function returns a new `ProcessedIntent`. Callers can discard the input if they wish.
- **D10 — No logging, no side effects.** Pure function. Logging is the responsibility of the future recognizer-adapter subphase.
- **D11 — `__all__` is declared.** One public symbol: `process_agregar_producto`.

## Risks / Trade-offs

- **[Risk] The processor assumes the `AGREGAR_PRODUCTO_CONTRACT` schema is stable.** If a future subphase adds a new requirement, the processor will pick it up automatically because it iterates the contract. If a future subphase **renames** a requirement, the resolver output and the contract may diverge silently. → Acceptable for the active subphase; the contract is owned by the team and a rename would be a deliberate change.
- **[Risk] The processor does not validate that the contract's `requirements` keys match the `resolved_data` keys.** → Acceptable for the active subphase: the processor reads the contract as the source of truth, so any extra keys in `resolved_data` are simply ignored.
- **[Trade-off] Status decision is `ready` vs `pending_resolution` only.** A future subphase may introduce `executed` / `rejected` / `failed` transitions, but those are handler-side concerns and out of scope here.

## Open Questions

- None. The function's signature, input fields, output shape, and the "no recognizer / no handler / no DB / no persistence" rule are all fixed by Subphase 3.6 in `project.md`.