## ADDED Requirements

### Requirement: Product-selection resolver emits diagnostic events through a sink

The `resolve_product_selection` function SHALL accept an optional `sink: DiagnosticSink` keyword argument that defaults to `NoopDiagnosticSink()`. The function SHALL emit a `ResolverCallStarted` event immediately before the catalog query and a `ResolverCallCompleted` event immediately after the recognizer result is consumed. The `Started` event SHALL carry the `call_id`, `turn_id`, the resolver class, the resolver method (`resolve_product_selection`), the resolver purpose (`product_selection_refinement`), the session id, the incoming text, the normalized text (if available), the intent, the source text, the quantity, the status before the call, the requirements before the call, the resolved data before the call, the candidate ids before the call, the candidate count, and a candidate catalog projection (the 12 fields already built for `detectar_productos`). The `Completed` event SHALL carry the call_id, the result type, the status after the call, the selected candidate id, the selected product name, the quantity after the call, the requirements after the call, the resolved data after the call, the candidate ids after the call, the candidate count after the call, the rejection reason (if any), the clarification message (if any), the raw result, and a matches list (one entry per `encontrados` / `encontrados_posibles` group with the candidate id, the candidate name, the score (if available), the match type, the matched text, and the accepted flag). The function SHALL NOT call `commit`, `rollback`, `flush`, `refresh`, `expire`, or `begin`; it SHALL NOT modify the session model; it SHALL NOT call handlers. The function SHALL NOT re-resolve the intent.

#### Scenario: Default sink is a no-op

- **WHEN** `resolve_product_selection(db, message, active_intent)` is called without a `sink` argument
- **THEN** the function returns the same `ProcessedIntent` it returned before this subphase and emits no event

#### Scenario: Started event captures the resolver input

- **WHEN** `resolve_product_selection(db, "picante", active_intent, *, sink=stub)` is called with `active_intent.status == "pending_resolution"` and `candidate_ids == [10, 11]`
- **THEN** the emitted `ResolverCallStarted` event carries `resolver_class="ProductSelectionContextResolver"`, `resolver_method="resolve_product_selection"`, `incoming_text="picante"`, `intent="agregar_producto"`, `status_before="pending_resolution"`, `candidate_ids_before=[10, 11]`, and the built candidate catalog

#### Scenario: Completed event captures the unique selection

- **WHEN** the recognizer returns exactly one candidate in `encontrados` and the resolver selects it
- **THEN** the emitted `ResolverCallCompleted` event carries `status_after="ready"`, `selected_candidate_id=<id>`, `candidate_ids_after=[]`, `candidate_count_after=0`, and the matches list with the single entry

#### Scenario: Completed event captures the narrowing branch

- **WHEN** the recognizer returns zero items in `encontrados` and three groups in `encontrados_posibles` that narrow the active candidates
- **THEN** the emitted `ResolverCallCompleted` event carries `status_after="pending_resolution"`, `candidate_ids_after=[<narrowed ids>]`, and the matches list with the three narrowed entries

#### Scenario: Completed event captures the unchanged branch

- **WHEN** the recognizer returns zero items in `encontrados` and an empty `encontrados_posibles`
- **THEN** the emitted `ResolverCallCompleted` event carries `result_type="ProcessedIntent"` (the same input), `status_after="pending_resolution"`, and `candidate_ids_after=[<original ids>]`

#### Scenario: Resolver does not re-resolve when sink is active

- **WHEN** the same `resolve_product_selection` is called with a `CollectingDiagnosticSink` and with a `NoopDiagnosticSink`
- **THEN** the `detectar_productos` call count is identical in both runs (1 call per resolve) and the catalog query runs exactly once
