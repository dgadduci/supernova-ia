## Context

Phase 3 (Intents) is now layering up the runtime: 3.1 (static contract), 3.2 (per-requirement state), 3.3 (per-intent envelope), 3.4 (conversation-wide state). The next layer is the *adapter* that turns recognizer output into the runtime envelope. The `recognizer_productos` is the LLM-based step that will land in a future subphase; it returns a recognizer-specific dict. `ProductIntentResolver` is the small, pure, well-defined translation from that dict into the `resolved_data` / `candidate_ids` / `unavailable_items` / `not_found_items` shape that `ProcessedIntent` (subphase 3.3) expects. It is the first leaf that actually touches recognizer data; no other intent adapter, no handler, no LLM call, no DB write.

## Goals / Non-Goals

**Goals:**

- Create a single Python file under `backend/intents/resolvers/` exporting one function `resolve_product_intent(raw: dict) -> dict`.
- The function takes a `dict` with four recognizer-shaped keys and returns a `dict` with four runtime-shaped keys.
- The function is **pure** — no I/O, no DB, no LLM, no intent contract application, no handler execution, no persistence.
- The file is importable: `from backend.intents.resolvers.product_intent_resolver import resolve_product_intent` works without side effects.
- One test covers: exact product found, multiple possible candidates, unavailable products, not-found products, and empty recognizer result.

**Non-Goals:**

- No LLM call, no async, no HTTP. The recognizer itself is a future subphase.
- No intent contract application, no handler invocation, no `IntentProcessor`. Those are future subphases.
- No persistence, no DB write, no Pydantic models on the input/output. The function accepts and returns plain dicts; the surrounding adapters handle the typed envelopes.
- No other resolvers (`cerrar_pedido_resolver`, etc.). One resolver per subphase.

## Decisions

- **D1 — The function is `resolve_product_intent(raw: dict) -> dict`.** Plain dicts on both sides. The function does not import any Pydantic model. The surrounding adapter (a future subphase) is responsible for wrapping the input/output into typed envelopes (`ProcessedIntent`, etc.).
- **D2 — Input shape: `raw` has four optional keys.** All four are tolerated if missing. Missing keys behave as empty collections:
  - `encontrados`: list of dicts, each `{id: int, cantidad: int}`. Confident matches.
  - `encontrados_posibles`: list of dicts, each `{id: int, cantidad?: int}` (cantidad optional). Plausible matches.
  - `encontrados_no_disponibles`: list of dicts, each `{source_text: str}` (or `{nombre: str}`; we standardize on `source_text` for consistency). Unavailable.
  - `no_encontrados`: list of dicts, each `{source_text: str}`. Unmatched.
  Each missing key defaults to `[]`. This makes the function robust to partial recognizer output and to the empty-result case.
- **D3 — Output shape: `resolved_data`, `candidate_ids`, `unavailable_items`, `not_found_items`.** Plain dicts, list values.
  - `resolved_data: dict[str, Any]` — at minimum `{"producto_presentacion_id": <int>, "cantidad": <int>}` for the single confident match. For multiple confident matches, the spec is ambiguous; this subphase assumes the active flow handles ONE item per intent (consistent with the `agregar_producto` contract). If the recognizer returns multiple confident matches, the resolver keeps the first and ignores the rest (this is a future concern to revisit if multi-item intents are added).
  - `candidate_ids: list[int]` — every `id` from `encontrados_posibles` collected in order. Used by the future handler to disambiguate via the WhatsApp channel.
  - `unavailable_items: list[str]` — every `source_text` from `encontrados_no_disponibles`.
  - `not_found_items: list[str]` — every `source_text` from `no_encontrados`.
- **D4 — Preserve the detected `cantidad` from `encontrados_posibles` when present.** If the recognizer is unsure but already extracted a quantity (e.g. "2 pizzas"), the resolver stores it in `resolved_data["cantidad"]` so the future handler has it. This avoids a second round-trip with the user just to ask "how many?".
- **D5 — `resolved_data` is constructed last, after `candidate_ids`.** The function reads `encontrados` first; if empty, it falls back to `encontrados_posibles[0]`'s `cantidad` for the `cantidad` slot. The `producto_presentacion_id` is left to the future handler to populate (it cannot be inferred from a list of candidates without disambiguation). The test for "multiple possible candidates" asserts this behavior.
- **D6 — Single confident match → populated `resolved_data`.** When `encontrados` has exactly one item, `resolved_data["producto_presentacion_id"]` and `resolved_data["cantidad"]` are populated. The function does not look at `candidate_ids` in that case.
- **D7 — Multiple confident matches → resolver keeps the first and ignores the rest.** Per D3, multi-item intents are out of scope. The first item wins; the rest are silently dropped. A future subphase may add a `MultipleMatchesError` for this case; today the behavior is documented in this decision.
- **D8 — No validation of input shape beyond `dict`.** The function does not raise on missing keys (D2), does not raise on items that are not dicts (the iteration will raise `TypeError`, which is the natural Python error). The active subphase does not introduce a `ValidationError` layer.
- **D9 — No import of Pydantic models.** Per D1. The function operates on plain dicts; the adapter layer (future) handles the typed envelopes.
- **D10 — No logging, no side effects.** Pure function. The future recognizer-adapter subphase can log around this function if needed.
- **D11 — File layout.** `backend/intents/resolvers/__init__.py` is an empty package marker. Future resolvers (`cerrar_pedido_resolver`, etc.) slot in alongside.

## Risks / Trade-offs

- **[Risk] Multi-confident-match inputs silently drop items.** → Acceptable for the active subphase: the spec is silent on this case, and the test only covers the single-confident case. Documented in D7. A future subphase can add a stricter policy.
- **[Risk] `source_text` vs `nombre` in the input shape.** The spec does not define the per-item key. We standardize on `source_text` for consistency with `ProcessedIntent.source_text`. If the recognizer uses a different key (e.g. `nombre`), the function will raise `KeyError`. → Acceptable; a future subphase can normalize the input.
- **[Trade-off] `resolved_data["producto_presentacion_id"]` is left empty when only candidates are present.** The future handler is responsible for picking from the candidates and asking the user to disambiguate. Today the resolver is purely a translation.

## Open Questions

- None. The function's input keys, output keys, and the "no intent contracts / no business rules / no persistence / no handler execution / limited to product recognition normalization" rule are all fixed by Subphase 3.5 in `project.md`.