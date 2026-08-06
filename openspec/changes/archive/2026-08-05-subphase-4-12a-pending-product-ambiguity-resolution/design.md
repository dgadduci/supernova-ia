## Context

The active pending context (`session.context_type == "product_selection"`) holds a `ProcessedIntent` whose `candidate_ids` enumerates the catalog rows the customer can choose from. `product_selection_context_service.resolve` already calls `resolve_product_selection`, which applies three narrow rules against the candidate-restricted catalog:

1. The real `FuzzyProductRecognizer.recognize` call (`detectar_productos`) over the restricted catalog — accepts unique (`encontrados`) and narrows on partial candidates (`encontrados_posibles`).
2. The presentacion-alias narrow step (`_narrow_by_presentacion_alias`) — picks by presentation token (`grande`, `chica`) and presentacion-alias-in-product-name.

What is missing for Subphase 4.12A is the deterministic reply vocabulary the customer can be expected to use after seeing a numbered clarification:

- numeric (`1`, `2`),
- positional (`primera`, `segunda`, `la primera`, `la opción dos`),
- exact normalized candidate name,
- exact token-set preference (`coca cola en lata` must select Coca-Cola Lata over Coca-Cola Zero Lata),
- differentiating tokens (`zero`, `coca zero`),
- contextual default descriptors (`común`, `normal`, `regular`, `original`),
- explicit exclusion (`la que no es zero`, `sin zero`, `no quiero la zero`),
- restricted fuzzy fallback over the persisted `candidate_ids`,
- remain ambiguous when evidence is insufficient.

The current resolver leaves these messages unchanged (the recognizer treats them as no-match or full-string match) and the conversation stalls with a re-prompt. Subphase 4.12A closes the gap with a pure, candidate-scoped resolver module and a one-line orchestration extension. The change must not touch embeddings, hybrid scoring, calibration, or the general recognizer.

## Goals / Non-Goals

**Goals:**

- Introduce a single pure resolver `resolve_pending_product_ambiguity` that closes the nine resolution layers in order against the persisted `candidate_ids` only.
- Wire the new resolver into `ProductSelectionContextService.resolve` as a sibling step invoked when the existing fragment path leaves the intent unchanged; the existing path continues to own presentacion aliases and fragment-based narrowing.
- Keep the existing pending-context contracts intact (no schema change, no migration, no router, no handler, no response builder, no transaction ownership change).
- Cover each resolution layer with focused pytest cases, plus a real-recognizer integration conversation reproducing the Coca-Cola Common vs Zero exchange.
- Cover a second generic ambiguity family (e.g. Pizza Tradicional vs Pizza Especial, or Empanada de Carne vs Empanada de Pollo) so the implementation is not hardcoded to Coca-Cola.

**Non-Goals:**

- No product-specific conditionals based on database IDs.
- No embeddings, vector search, hybrid scoring, threshold, calibration dataset, or calibration policy change.
- No authoritative hybrid mode activation.
- No redesign of the general recognizer (`FuzzyProductRecognizer` / `detectar_productos`).
- No global alias table or product-recognition shadow-mode change.
- No FastAPI endpoint, router, response builder, or handler change.
- No pending-context dispatch, execution, transaction, or persistence ownership change.
- No customer response shaping.

## Decisions

### Decision 1: New pure sibling module, not an extension of the existing resolver

- **Choice**: Add `backend/intents/context/pending_product_ambiguity_resolver.py` exporting only `resolve_pending_product_ambiguity` through `__all__`. Do not modify `product_selection_context_resolver.py`.
- **Rationale**: The existing resolver owns the `detectar_productos` call and the presentacion-alias narrow step. Folding the new vocabulary (numeric / positional / negation) into it would couple two unrelated concerns (fuzzy narrowing vs. deterministic reply vocabulary). A sibling module preserves the existing scenarios verbatim (Subphase 3.12, 3.32.x) and keeps each layer testable in isolation. The orchestration service composes them in priority order.
- **Alternatives considered**:
  - *Inline the new logic in `product_selection_context_service.resolve`* → rejected: hides the 9-layer contract, makes unit testing harder, and would leak layer ordering into the orchestration service.
  - *Add a new sibling resolver inside the existing `product_selection_context_resolver.py` file* → rejected: the file already has its own diagnostic-sink contract and would gain two unrelated responsibilities.

### Decision 2: Resolve only against `active_intent.candidate_ids`

- **Choice**: The new resolver receives the active intent's `candidate_ids` plus a catalog projection built from those ids (the same 12-field shape `detectar_productos` consumes) and never reads or compares against the full commerce catalog. The catalog is loaded by the existing `ProductoQueryService.list_presentaciones_by_ids(active_intent.candidate_ids)` exactly once per call.
- **Rationale**: This is the Subphase 4.12A invariant. Widening the catalog during clarification would silently invite mis-resolution from full-catalog fuzzy hits that the customer never saw. The narrow load is also cheap (typically 2–10 rows).
- **Alternatives considered**:
  - *Reuse the restricted catalog already loaded by `resolve_product_selection`* → rejected: the new resolver must be callable independently of the existing path and must not depend on the existing resolver's diagnostic-sink lifecycle.

### Decision 3: Strict 9-layer evaluation order

The layers run in order; the first layer that produces a definitive answer wins, and later layers do not run for the same call.

1. **Numeric** — if the normalized message contains exactly one Arabic numeral `n` and `1 ≤ n ≤ len(candidate_ids)`, select `candidate_ids[n - 1]`. Accepts `"1"`, `"2"`, `"la 1"`, `"opción 2"`.
2. **Positional** — Spanish ordinal tokens (`primera`, `primero`, `segunda`, `segundo`, `tercera`, `tercero`, `última`, `último`, `la primera`, `la segunda`, `la opción dos`, `la opción 2`) map to indices. Out-of-range indices are ignored.
3. **Exact normalized full-name** — if the normalized message equals the normalized candidate name (`producto_nombre` + `presentacion_descripcion` or `producto_nombre` alone when only one candidate has no presentation suffix), select that candidate.
4. **Exact token-set match with filler stripping, shared-core precondition, subset preference, and distinguishing-token penalty** — Strip the implementation-defined `FILLER_TOKENS` set (MUST include `en`; MAY include other common Spanish prepositions/articles such as `de`, `la`, `el`, `los`, `las`, `del`, `al`) from both the candidate full-name normalized token set and the message normalized token set, producing `candidate_core` and `message_core`. Selection then proceeds by strict priority:
   - (a) **Shared-core precondition (mandatory guard)** — a candidate is eligible for Layer 4 ranking only when `candidate_core ∩ message_core` is non-empty. Candidates whose `candidate_core` has zero overlap with `message_core` SHALL be excluded from the ranking. If no candidate has a non-empty shared core with the message, this layer does not select and the next layer is consulted.
   - (b) **Exact match** — if exactly one eligible candidate has `candidate_core == message_core`, that candidate is selected.
   - (c) **Subset preference with distinguishing-token penalty** — otherwise, rank the eligible candidates by: (i) prefer `candidate_core ⊆ message_core` (no extra distinguishing tokens in the candidate), then (ii) minimise `len(candidate_core - message_core)` (penalise extra distinguishing tokens such as `zero`), then (iii) minimise `len(message_core - candidate_core)` (prefer the candidate that covers the most of the reply). The unique top-ranked candidate is selected; if two or more candidates tie on the ranking, this layer does not select and the next layer is consulted. Total candidate token count (`len(candidate_core)`) is NOT a ranking criterion — a unique rank caused solely by token-count differences (with all of (i), (ii), (iii) tied) SHALL leave the layer fall-through to the next layer.
   - When `message_core` is empty (every token was a filler), this layer does not select and the next layer is consulted.

   For `coca cola en lata` against Common Lata and Zero Lata, `message_core` (after stripping the filler `en`) is `{coca, cola, lata}`. Both candidates pass the shared-core precondition (Common Lata shares `{coca, cola, lata}` and Zero Lata shares `{coca, cola, lata}`). Under rule (b), Common Lata's `candidate_core` equals `message_core` exactly, so rule (b) selects Common Lata uniquely. Zero Lata would otherwise carry the extra distinguishing token `zero` under rule (c). An unrelated reply such as `banana split` produces a `message_core` with zero overlap against either candidate; both candidates are ineligible and Layer 4 falls through. Ties (including ties that arise only from differences in total candidate token count) remain ambiguous.
5. **Differentiating token** — if exactly one candidate's `producto_nombre` normalized tokens contain a token from the message that no other candidate's normalized `producto_nombre` contains, select that candidate. (`zero` → Coca-Cola Zero Lata.)
6. **Contextual default descriptor** — the descriptors `común`, `normal`, `regular`, `original`, `clásica`, `clásico` map to the candidate that does NOT carry any distinguishing variant token (e.g. `zero`, `light`, `diet`, `sin azúcar`). When every candidate carries a distinguishing token the descriptor is ignored.
7. **Explicit exclusion** — phrases like `la que no es zero`, `sin zero`, `no quiero la zero`, `que no tenga zero`, `la otra` are parsed for the excluded token; if exactly one candidate matches the negation, select it.
8. **Restricted fuzzy fallback** — run a narrow RapidFuzz `partial_ratio` against each candidate's normalized `producto_nombre + presentacion_descripcion` using a threshold of 85 (mirroring the existing recognizer's threshold style). Only consider candidates already in `candidate_ids`. If exactly one candidate clears the threshold, select it.
9. **Remain ambiguous** — return the input `active_intent` unchanged (same instance, `is` comparison).

**Rationale**: Deterministic, candidate-scoped, predictable for tests and for the customer. The 9 layers are individually simple; the contract is in the ordering, not in any heuristic.

**Alternatives considered**:
  - *LLM re-classification* → rejected: Subphase 4.12A is intentionally LLM-free for this layer (the customer has already seen a numbered list; an LLM call would be slower, more expensive, and harder to audit).
  - *Single combined scoring pass* → rejected: layers 1, 2, 7 are categorical (numeric, positional, negation); combining them with token-set scoring would lose the deterministic priority.

### Decision 4: Composition in the orchestration service

- **Choice**: `ProductSelectionContextService.resolve` loads the restricted catalog via `ProductoQueryService.list_presentaciones_by_ids(active_intent.candidate_ids)` exactly once and calls `resolve_product_selection(active_intent, catalog)` first. The existing path's result is bound to `fragment_result`. If `fragment_result.status == "ready"`, the orchestration returns `fragment_result` directly and the new resolver is NOT consulted. Otherwise (i.e. the existing path did not resolve uniquely):
  - The orchestration passes **`fragment_result` (NOT the original `active_intent`)** to `resolve_pending_product_ambiguity`.
  - The catalog projection passed to the new resolver is the in-memory catalog already loaded, **filtered to `fragment_result.candidate_ids`**. The orchestration SHALL NOT reload the catalog via `list_presentaciones_by_ids` again, and SHALL NOT widen the catalog beyond `fragment_result.candidate_ids`.
  - The new resolver therefore cannot reintroduce a candidate that the existing narrowing path discarded because such a candidate is absent from the catalog projection.
  - If the new resolver returns a `ready` intent, the orchestration returns it. If the new resolver does not resolve (`fragment_result` preserved or further narrowed by the new resolver), the orchestration returns `fragment_result` (the existing path's narrowed candidate list).
- **Rationale**: Passing `fragment_result` instead of `active_intent` is what physically enforces the "never reintroduce a discarded candidate" invariant: the new resolver's catalog is restricted to what the existing path already kept. Returning `fragment_result` when the new resolver doesn't resolve preserves the existing narrowed-but-still-pending semantics so the next message can be measured against the same narrowed candidate set.
- **Alternatives considered**:
  - *Always call both and prefer the new resolver's verdict* → rejected: would regress existing fragment-resolution scenarios (e.g. `picante` against Empanada de Carne vs Empanada de Carne Picante).
  - *Replace the existing fragment path entirely* → rejected: violates the "preserve existing contracts" constraint and would break Subphase 3.32 scenarios.
  - *Pass the original `active_intent` to the new resolver* → rejected: would let the new resolver reintroduce candidates the existing path discarded and would silently undo fragment-based narrowing.

### Decision 5: No product-specific ID conditionals

- **Choice**: All layer logic is generic over the catalog rows. The implementation MUST NOT branch on `producto_id`, `presentacion_id`, `producto_nombre` strings like `coca-cola`, or any other product-specific identifier. The Coca-Cola Common vs Zero scenario is exercised through the test fixture, not through hardcoded rules.
- **Rationale**: Subphase 4.12A requires "do not add product-specific conditionals based on database IDs". A second generic family (e.g. `Pizza Muzzarella` vs `Pizza Napolitana`) is added to the test suite to prove the rules are generic.
- **Alternatives considered**: a per-product alias map → rejected: would violate the constraint and would create global state.

### Decision 6: Test layout

- **Choice**: One focused pytest file `backend/tests/test_pending_product_ambiguity_resolution.py` per the existing pattern (`test_product_selection_context_resolver_*`, `test_order_line_selection_resolver.py`, etc.). Each layer has a dedicated test function with explicit pass / fail / remain-ambiguous cases. The Coca-Cola Common vs Zero conversation is reproduced as an end-to-end test using the existing `dispatch_pending_context` flow against `supernova_test`. A second generic family is added as a parallel scenario using `Pizza Muzzarella Tradicional` vs `Pizza Muzzarella Especial` (or another pair that proves the rules are generic).
- **Rationale**: Mirrors the existing pending-context test structure. Keeps each layer individually auditable. The conversation test pins the customer-visible behaviour.
- **Alternatives considered**: appending tests to `backend/tests/api_smoke.py` → rejected: the new module deserves its own focused file, matching the existing `test_*` naming convention.

## Risks / Trade-offs

- **Risk**: The token-set penalty scoring could mis-rank edge cases where a candidate name shares most tokens with the customer message but the customer mentions an extra distinguishing word.
  - **Mitigation**: Layer 4 (exact token-set with filler stripping, subset preference, and distinguishing-token penalty) and Layer 5 (differentiating token) are evaluated in order; if either uniquely identifies a candidate, the implementation picks that candidate strictly. `coca cola en lata` resolves to Common Lata via Layer 4's exact-match rule (the filler `en` is stripped and the resulting message core equals Common Lata's candidate core). Zero Lata would otherwise incur the extra-distinguishing-token penalty for `zero`. Tests include `coca cola en lata` → Common Lata and `coca zero` → Zero Lata as pinned cases.
- **Risk**: The contextual default descriptor (`común`, `normal`, `regular`, `original`) could over-trigger on a candidate whose name legitimately contains the token (e.g. `Pizza Común` vs `Pizza Especial`).
  - **Mitigation**: Layer 6 only fires when one candidate lacks a distinguishing variant token. Tests cover both the "all candidates have variants" (descriptor ignored → remain ambiguous) and the "one candidate has no variant" (descriptor selects the variant-free candidate) cases.
- **Risk**: Numeric/positional interpretation could mis-fire on a customer reply that contains a year or a quantity (`"2 pizzas"`).
  - **Mitigation**: Layer 1 (numeric) only fires when the normalized message is a single token or `la <n>` / `opción <n>` / `número <n>`; a message containing any other content-bearing token after normalization falls through. Layer 2 (positional) is similarly constrained to ordinal tokens. The Coca-Cola test fixture (`1`, `primera`, `coca cola en lata`, `la que no es zero`) is pinned in the test suite.
- **Risk**: Restricted fuzzy fallback (Layer 8) could over-trigger and silently select a candidate the customer did not intend.
  - **Mitigation**: Threshold of 85 (matching the recognizer's partial-ratio style); the fallback is the last non-trivial layer before `remain ambiguous`. The test suite includes a "vague answer" case (e.g. `"no sé"`) that asserts the intent remains unchanged.
- **Risk**: Composition order could regress existing fragment-resolution scenarios.
  - **Mitigation**: The full existing pending-context and end-to-end suites (`api_smoke.py`, `test_agregar_producto_*`, `test_incoming_message_*`) must stay green. The composition rule is conservative (existing path wins if `ready`).

## Migration Plan

No migration. No schema change, no Alembic revision, no data backfill, no environment variable change. The change is a code-only extension that adds a new module and one method call inside the existing orchestration service. Rollback is a single revert: remove the new module, remove the one-line call from `ProductSelectionContextService.resolve`, drop the new test file. No customer-visible regression because the existing fragment path remains authoritative when it resolves.

## Open Questions

- None blocking. The 9-layer contract, the candidate-scope invariant, and the composition rule are specified explicitly in Subphase 4.12A and in the existing pending-context modules. The second generic ambiguity family will be chosen during implementation (Pizza Tradicional vs Especial is the leading candidate) and is exercised by the integration test, not by hardcoded logic.
