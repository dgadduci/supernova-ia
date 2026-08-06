# Pending Product Ambiguity Resolution

## Purpose

Provide a single pure-with-respect-to-its-own-state function that resolves a pending `PRODUCT_SELECTION` `ProcessedIntent` against the active `candidate_ids` using a deterministic 9-layer reply vocabulary (numeric, positional, exact normalized full-name, exact token-set after filler stripping with subset preference and distinguishing-token penalty, differentiating token, contextual default descriptors, explicit negation/exclusion, restricted fuzzy fallback, remain ambiguous). The function is layered as a sibling of `ProductSelectionContextResolver`, never queries the full commerce catalog, and exposes only the resolver function itself (no handler invocation, no `PendingIntentService` call, no session mutation, no commit, no flush, no persistence, no schema change, no router, no endpoint, no embeddings, no hybrid scoring, no calibration, no global alias table change).

## ADDED Requirements

### Requirement: Function exists
The system SHALL export a single function `resolve_pending_product_ambiguity(message: str, active_intent: ProcessedIntent, productos_presentaciones: list[dict]) -> ProcessedIntent` from `backend.intents.context.pending_product_ambiguity_resolver`. The function SHALL be importable without side effects, errors, or required dependencies beyond SQLAlchemy, the existing Phase 3 modules, and the standard library. The function SHALL NOT modify the `Session` model, SHALL NOT persist, SHALL NOT commit, SHALL NOT call handlers, SHALL NOT call repositories, and SHALL NOT generate responses.

#### Scenario: Function is importable
- **WHEN** any module executes `from backend.intents.context.pending_product_ambiguity_resolver import resolve_pending_product_ambiguity`
- **THEN** the import completes without raising and the binding is a callable

#### Scenario: Only one public symbol
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"resolve_pending_product_ambiguity"}`

### Requirement: Input validation
The function SHALL validate `active_intent`. If `active_intent.status` is not `"pending_resolution"` OR `active_intent.candidate_ids` is empty, the function SHALL return `active_intent` unchanged (same instance, `is` comparison).

#### Scenario: Returns unchanged when status is not pending_resolution
- **WHEN** the test calls `resolve_pending_product_ambiguity("1", intent_with_status_ready, catalog)`
- **THEN** the result is `intent_with_status_ready` (the same instance, `is` comparison)

#### Scenario: Returns unchanged when candidate_ids is empty
- **WHEN** the test calls `resolve_pending_product_ambiguity("1", intent_with_empty_candidates, catalog)`
- **THEN** the result is `intent_with_empty_candidates` (the same instance)

### Requirement: Catalog restricted to candidate_ids
The function SHALL accept `productos_presentaciones` as an argument and SHALL NEVER issue its own SQLAlchemy query. The catalog projection SHALL contain only rows whose `producto_presentacion_id` is in `active_intent.candidate_ids`; rows outside this set SHALL be ignored even if they appear in the input list.

#### Scenario: Catalog rows outside candidate_ids are ignored
- **WHEN** the input `active_intent.candidate_ids == [1, 2]` and the catalog contains rows for ids `[1, 2, 999]`
- **THEN** the function does not consult row `999` for any layer; the resolution outcome only considers ids `1` and `2`

### Requirement: Layer 1 — numeric selection
The function SHALL resolve the message as a numeric selection when the normalized message contains exactly one Arabic numeral `n` and `1 ≤ n ≤ len(candidate_ids)`. Accepted shapes are `"1"`, `"2"`, `"la 1"`, `"la 2"`, `"opción 1"`, `"opción 2"`, `"número 1"`, `"número 2"`. When the numeric condition is met, the function SHALL return a new `ProcessedIntent` with `resolved_data["producto_presentacion_id"] == candidate_ids[n - 1]`, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, the original `cantidad` preserved, and `status == "ready"` when all required requirements are completed.

#### Scenario: Numeric "1" selects the first candidate
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` (Common Lata first, Zero Lata second) and the message is `"1"`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == CocaColaLata.id`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved

#### Scenario: Numeric "2" selects the second candidate
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"2"`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == CocaColaZeroLata.id`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved

#### Scenario: Out-of-range numeric is ignored
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` (length 2) and the message is `"3"`
- **THEN** the function falls through to later layers (the numeric layer does not select) and the intent is not resolved by Layer 1

### Requirement: Layer 2 — positional selection
The function SHALL resolve the message as a positional selection when the normalized message contains a Spanish ordinal token mapping to an in-range index. Accepted shapes are `"primera"`, `"primero"`, `"segunda"`, `"segundo"`, `"tercera"`, `"tercero"`, `"última"`, `"último"`, `"la primera"`, `"la segunda"`, `"la opción dos"`, `"la opción 2"`, `"la 1"`, `"la 2"` (also covered by Layer 1 if the message has no other content). When the positional condition is met, the function SHALL return a new `ProcessedIntent` with `resolved_data["producto_presentacion_id"] == candidate_ids[index]`, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, the original `cantidad` preserved, and `status == "ready"` when all required requirements are completed.

#### Scenario: "primera" selects the first candidate
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"primera"`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == CocaColaLata.id`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved

#### Scenario: "segunda" selects the second candidate
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"segunda"`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == CocaColaZeroLata.id`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved

#### Scenario: "la opción dos" selects the second candidate
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"la opción dos"`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == CocaColaZeroLata.id`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved

### Requirement: Layer 3 — exact normalized full-name match
The function SHALL resolve the message by exact normalized full-name match when the normalized message equals the normalized candidate full name (concatenation of `producto_nombre` and `presentacion_descripcion`, whitespace-separated, with all diacritics and accents stripped, lowercased). When the condition is met for exactly one candidate, the function SHALL return a new `ProcessedIntent` with that candidate selected. When the condition is met for zero or more than one candidate, this layer does not select and the next layer is consulted.

#### Scenario: Exact full-name match selects the candidate
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message normalized equals `"coca cola zero lata"`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == CocaColaZeroLata.id`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved

#### Scenario: Exact full-name match is case-insensitive and accent-insensitive
- **WHEN** the message is `"Coca-Cola Zero Lata"` (mixed case, hyphen) and the catalog has `producto_nombre == "Coca-Cola Zero"` and `presentacion_descripcion == "Lata"`
- **THEN** the normalized equality holds and the candidate is selected

### Requirement: Layer 4 — exact token-set match with filler stripping, shared-core precondition, subset preference, and distinguishing-token penalty
The function SHALL resolve the message by exact token-set match (with removable filler tokens such as `en` stripped) when no earlier layer has selected. The function SHALL:

1. Define a module-private set `FILLER_TOKENS` of removable filler tokens. The set **MUST include `en`** and MAY include other common Spanish prepositions/articles (e.g. `de`, `la`, `el`, `los`, `las`, `del`, `al`). The set SHALL be defined as a module-level constant and SHALL NOT be sourced from any external configuration, database, or remote service.
2. Normalize the message into a token set `message_tokens` (lower-case, whitespace-split, diacritics stripped) and remove `FILLER_TOKENS` to obtain `message_core`.
3. For each candidate, normalize `producto_nombre + " " + presentacion_descripcion` into a token set `candidate_tokens` and remove `FILLER_TOKENS` to obtain `candidate_core`.
4. **Shared-core precondition (mandatory guard)** — a candidate is eligible for Layer 4 ranking only when `candidate_core ∩ message_core` is non-empty. Candidates whose `candidate_core` has zero overlap with `message_core` SHALL be excluded from the Layer 4 ranking. If no candidate has a non-empty shared core with the message, this layer SHALL NOT select and the next layer SHALL be consulted.
5. **Exact match priority**: among the eligible candidates, if exactly one candidate has `candidate_core == message_core`, that candidate SHALL be selected.
6. **Subset preference with distinguishing-token penalty**: if no eligible candidate clears rule 5, candidates SHALL be ranked by the following strict priority: (i) prefer `candidate_core ⊆ message_core` (no extra distinguishing tokens in the candidate); (ii) among those, minimise `len(candidate_core - message_core)` (penalise extra distinguishing tokens such as `zero`); (iii) among those, minimise `len(message_core - candidate_core)` (prefer the candidate that covers the most of the reply). The unique top-ranked candidate SHALL be selected.
7. **Ties remain ambiguous**: if two or more eligible candidates tie on the ranking in rule 6, this layer SHALL NOT select and the next layer SHALL be consulted. Total candidate core token count (`len(candidate_core)`) is explicitly NOT a ranking criterion; a unique ranking caused only by token-count differences (with all of (i), (ii), (iii) tied) SHALL leave this layer fall-through to the next layer.
8. **Empty core**: if `message_core` is empty (every token in the normalized message was a filler), this layer SHALL NOT select and the next layer SHALL be consulted.

#### Scenario: "coca cola en lata" selects Common Lata over Zero Lata
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"coca cola en lata"`
- **THEN** after stripping filler tokens (`en`) from both sides, `message_core == {coca, cola, lata}` equals Common Lata's `candidate_core` exactly; both candidates pass rule 4 (shared-core precondition); rule 5 then selects Common Lata uniquely; Zero Lata's `candidate_core` includes the extra distinguishing token `zero` and would otherwise be penalised under rule 6

#### Scenario: Equal token sets leave the intent for the next layer
- **WHEN** two or more candidates achieve the same rank under Layer 4 rule 6 (e.g. tie on `candidate_core ⊆ message_core` and on both penalty metrics)
- **THEN** the layer does not select and the function falls through to Layer 5

#### Scenario: Empty message core after filler stripping
- **WHEN** the normalized message consists solely of filler tokens (e.g. the message is `"en"` and `en` is in `FILLER_TOKENS`)
- **THEN** `message_core` is empty, this layer does not select, and the function falls through to Layer 5

#### Scenario: Unrelated reply with zero shared core tokens remains unresolved
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"banana split"` (whose normalized tokens share zero elements with either candidate's normalized full-name token set)
- **THEN** neither candidate has a non-empty shared core with the message, rule 4 excludes both candidates, this layer SHALL NOT select, and the function falls through to Layer 5

#### Scenario: Unique ranking caused only by token-count differences does not select
- **WHEN** two or more eligible candidates tie on rule 6's criteria (i), (ii), and (iii) but differ only in total candidate core token count (e.g. one candidate has `len(candidate_core) == 5` and another has `len(candidate_core) == 3`, with `candidate_core - message_core` and `message_core - candidate_core` identical for both)
- **THEN** the layer does not select (token-count is not a ranking criterion), and the function falls through to Layer 5

### Requirement: Layer 5 — differentiating-token match
The function SHALL resolve the message by differentiating token when the normalized message contains exactly one token that appears in exactly one candidate's normalized `producto_nombre` and does NOT appear in any other active candidate's normalized `producto_nombre`. When the condition is met, the function SHALL return a new `ProcessedIntent` with that candidate selected.

#### Scenario: "zero" differentiates Zero Lata
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"zero"`
- **THEN** `zero` appears only in Coca-Cola Zero Lata's `producto_nombre`; the returned intent has `resolved_data["producto_presentacion_id"] == CocaColaZeroLata.id`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved

#### Scenario: "coca zero" differentiates Zero Lata
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"coca zero"`
- **THEN** `coca` is shared and `zero` is unique to Zero Lata; the returned intent selects Zero Lata

### Requirement: Layer 6 — contextual default descriptors
The function SHALL recognise the contextual default descriptors `común`, `comun`, `normal`, `regular`, `original`, `clásica`, `clasica`, `clásico`, `clasico`, `estándar`, `estandar`. When the normalized message contains exactly one of these tokens AND exactly one candidate does NOT carry any distinguishing variant token (`zero`, `light`, `diet`, `sin azúcar`, `sin azucar`, `baja en azúcar`, `baja en azucar`, or any token present in one candidate's `producto_nombre` but absent in another), that variant-free candidate SHALL be selected. When all candidates carry a distinguishing variant, this layer does not select and the next layer is consulted.

#### Scenario: "común" selects Common Lata
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"común"`
- **THEN** Coca-Cola Lata has no distinguishing variant (only `coca`, `cola`, `lata`) and Coca-Cola Zero Lata carries `zero`; the returned intent has `resolved_data["producto_presentacion_id"] == CocaColaLata.id`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved

#### Scenario: "normal" / "regular" / "original" also select Common Lata
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"normal"` (or `"regular"` or `"original"`)
- **THEN** the same candidate (Common Lata) is selected

### Requirement: Layer 7 — explicit exclusion
The function SHALL recognise explicit exclusion phrases: `la que no es <token>`, `la que no tenga <token>`, `la que no tiene <token>`, `sin <token>`, `no quiero la <token>`, `no la <token>`, `la otra`. When the phrase matches and exactly one candidate's normalized `producto_nombre` does NOT contain the excluded token, that candidate SHALL be selected. When the excluded token is absent from every candidate's `producto_nombre`, this layer does not select.

#### Scenario: "la que no es zero" selects Common Lata
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"la que no es zero"`
- **THEN** the excluded token is `zero`; Common Lata does not contain `zero` and Zero Lata does; the returned intent has `resolved_data["producto_presentacion_id"] == CocaColaLata.id`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved

#### Scenario: "sin zero" selects Common Lata
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"sin zero"`
- **THEN** the excluded token is `zero`; Common Lata is selected

#### Scenario: "no quiero la zero" selects Common Lata
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"no quiero la zero"`
- **THEN** the excluded token is `zero`; Common Lata is selected

#### Scenario: Excluded token not present in any candidate falls through
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"la que no es manzana"`
- **THEN** the excluded token `manzana` is not in any candidate; this layer does not select and the next layer is consulted

### Requirement: Layer 8 — restricted fuzzy fallback
The function SHALL run a narrow RapidFuzz `partial_ratio` against each candidate's normalized `producto_nombre + " " + presentacion_descripcion` (whitespace-joined) using a threshold of 85. Only candidates whose `producto_presentacion_id` is in `active_intent.candidate_ids` are scored. The function SHALL compute the score against the same normalized message tokens used by the earlier layers. When exactly one candidate clears the threshold and its score is strictly greater than every other candidate's score, that candidate SHALL be selected. When two or more candidates clear the threshold or the highest score is tied, this layer does not select.

#### Scenario: Close fuzzy match selects the only candidate above threshold
- **WHEN** the active candidates are `[PizzaMuzzarellaTradicional, PizzaMuzzarellaEspecial]` and the message is `"pizza muzza tradicional"` (with one missing accent and one extra token)
- **THEN** `PizzaMuzzarellaTradicional` clears the partial-ratio threshold and `PizzaMuzzarellaEspecial` does not; the returned intent selects `PizzaMuzzarellaTradicional`

#### Scenario: Tied fuzzy scores fall through to remain ambiguous
- **WHEN** two candidates tie on the strict highest partial-ratio score (e.g. both score 87)
- **THEN** this layer does not select and the next layer is consulted

### Requirement: Layer 9 — remain ambiguous
When no layer produces a definitive answer, the function SHALL return `active_intent` unchanged (same instance, `is` comparison). The function SHALL NEVER silently select a candidate by candidate order, by string similarity alone, or by any other heuristic not enumerated in layers 1–8.

#### Scenario: Vague answer remains ambiguous
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"no sé"` or `"ok"`
- **THEN** the returned intent is the input intent (same instance), `candidate_ids` is preserved, and `status` remains `"pending_resolution"`

#### Scenario: No candidate matches any layer
- **WHEN** the active candidates are `[CocaColaLata, CocaColaZeroLata]` and the message is `"quiero hablar con un humano"`
- **THEN** the function returns the input intent unchanged

### Requirement: Strict evaluation order
The function SHALL evaluate the nine layers in the documented order (1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9). The first layer that produces a definitive answer wins. Later layers SHALL NOT run for the same call once an earlier layer has selected a candidate. The function SHALL NOT combine layers (e.g. a fuzzy score that is "almost" a match does not pre-empt a token-set match).

#### Scenario: Layer 1 wins over Layer 5 when both could apply
- **WHEN** the message is `"1"` and the active candidates are `[CocaColaLata, CocaColaZeroLata]`
- **THEN** the function returns the candidate selected by Layer 1 (Common Lata) without consulting Layer 5 or any later layer

### Requirement: No side effects
The function SHALL NOT call `commit` on the session, SHALL NOT call `flush` on the session, SHALL NOT call `close` on the session, SHALL NOT modify the `Session` model, SHALL NOT mutate `active_intent` in place, SHALL NOT call handlers, SHALL NOT call repositories, SHALL NOT issue SQLAlchemy queries, and SHALL NOT log anything. The function SHALL return either the input `active_intent` (same instance) or a new `ProcessedIntent` constructed via `model_copy(update=...)` or direct construction.

#### Scenario: Function does not commit
- **WHEN** the test calls the function with a mock session
- **THEN** the session's `commit` is not called

#### Scenario: Function does not modify the active intent in place
- **WHEN** the test calls the function with a sample `active_intent`
- **THEN** the input `active_intent` instance is not mutated (`is` comparison preserved when the function returns the input unchanged)

### Requirement: Public surface is limited
The system SHALL expose only `resolve_pending_product_ambiguity` from `backend.intents.context.pending_product_ambiguity_resolver` through `__all__`. Internal helpers (token normalization, layer detectors, score functions) SHALL be private to the module and SHALL NOT be re-exported from `__init__.py` or any sibling module.

#### Scenario: Only the resolver function is exported
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"resolve_pending_product_ambiguity"}`

#### Scenario: Module package contains only the resolver file
- **WHEN** the test lists Python files under `backend/intents/context/` after this change lands
- **THEN** the file set includes `pending_product_ambiguity_resolver.py` and the existing files (`__init__.py`, `context_type_resolver.py`, `pending_context_service.py`, `product_selection_context_resolver.py`, `product_selection_context_service.py`, `order_line_selection_resolver.py`, `product_modification_resolver.py`); no other new files are added

### Requirement: Real integration with the pending-context dispatch
The active subphase MUST include an end-to-end integration test that reproduces the Coca-Cola Common vs Zero clarification conversation through the existing `dispatch_pending_context` entry point against `supernova_test` (no mocking of the existing orchestrators, recognizer, dispatcher, handler, or services). The test MUST cover at least three sequential messages: the initial ambiguous message that establishes the pending context with two candidates, the numeric / positional / exact-name / token-set / differentiating / default / exclusion reply that resolves to one of the candidates, and the executed confirmation. A second generic ambiguity family (e.g. `Pizza Muzzarella Tradicional` vs `Pizza Muzzarella Especial`) MUST be exercised by a parallel integration test using the same entry point.

#### Scenario: Coca-Cola Common vs Zero full conversation
- **WHEN** the test seeds two `ProductoPresentacion` rows for `Coca-Cola Común Lata` and `Coca-Cola Zero Lata` linked to the same comercio, runs `dispatch_pending_context(db, session, "1")` (or any of `"primera"`, `"coca cola en lata"`, `"común"`, `"normal"`, `"regular"`, `"la que no es zero"`, `"sin zero"`)
- **THEN** the returned intent has `status == "executed"`, exactly one `PedidoProducto` row exists for the draft `pedido_id` whose `presentacion_id` corresponds to `Coca-Cola Común Lata`, `session.pending_intents` is empty, and `session.context_type is None`

#### Scenario: Coca-Cola Zero selection via differentiating token
- **WHEN** the test runs the same setup and runs `dispatch_pending_context(db, session, "zero")` (or any of `"2"`, `"segunda"`, `"coca zero"`, `"la zero"`)
- **THEN** the returned intent has `status == "executed"`, exactly one `PedidoProducto` row exists for the draft `pedido_id` whose `presentacion_id` corresponds to `Coca-Cola Zero Lata`, `session.pending_intents` is empty, and `session.context_type is None`

#### Scenario: Second generic family — Pizza Tradicional vs Especial
- **WHEN** the test seeds two `ProductoPresentacion` rows for `Pizza Muzzarella Tradicional` and `Pizza Muzzarella Especial` linked to the same comercio, runs `dispatch_pending_context(db, session, "tradicional")` (or `"1"`, `"primera"`, `"la tradicional"`, `"la que no es especial"`)
- **THEN** the returned intent has `status == "executed"`, exactly one `PedidoProducto` row exists for the draft `pedido_id` whose `presentacion_id` corresponds to `Pizza Muzzarella Tradicional`, `session.pending_intents` is empty, and `session.context_type is None`

#### Scenario: Vague answer remains ambiguous through the dispatch path
- **WHEN** the test seeds the Coca-Cola pair and runs `dispatch_pending_context(db, session, "no sé")`
- **THEN** the returned intent has `status == "pending_resolution"`, `session.context_type == "product_selection"` is preserved, no `PedidoProducto` row exists for the draft `pedido_id`, and the active pending intent's `candidate_ids` is preserved

### Requirement: Existing pending-context behaviour is preserved
The function SHALL NOT alter the existing pending-context contracts. The existing `resolve_product_selection` function (Subphases 3.12, 3.32.x) SHALL continue to own presentacion-alias and fragment-based narrowing; the new resolver SHALL only be invoked as a sibling step. Existing test suites (`api_smoke.py`, `test_agregar_producto_*`, `test_incoming_message_*`, `test_pending_context_*`, `test_product_selection_context_resolver_*`) SHALL remain green after this change lands.

#### Scenario: Existing fragment path remains authoritative
- **WHEN** the active candidates are `[EmpanadaCarneUnidad, EmpanadaCarnePicanteUnidad]` and the message is `"picante"` (a fragment covered by the existing `_narrow_by_presentacion_alias` path)
- **THEN** the existing `resolve_product_selection` selects Empanada de Carne Picante Unidad and returns `status == "ready"`; the new resolver is not consulted and the existing scenario remains green

#### Scenario: Existing recognizer-based unique match remains authoritative
- **WHEN** the active candidates are `[PizzaMuzzarellaChica, PizzaMuzzarellaGrande]` and the message is `"la grande"` (a presentation-alias match covered by `resolve_product_selection`)
- **THEN** the existing path selects the Grande candidate and returns `status == "ready"`; the new resolver is not consulted and the existing scenario remains green
