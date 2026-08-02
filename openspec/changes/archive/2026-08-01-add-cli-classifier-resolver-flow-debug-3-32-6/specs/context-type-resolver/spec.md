## ADDED Requirements

### Requirement: Context-type-resolver emits diagnostic events through a sink

The `resolve_context_type` function SHALL accept an optional `sink: DiagnosticSink` keyword argument that defaults to `NoopDiagnosticSink()`. The function SHALL emit a `ResolverCallStarted` event immediately before the `PendingIntent` lookup and a `ResolverCallCompleted` event immediately after the `ContextType` is determined. The `Started` event SHALL carry the `call_id`, `turn_id`, the resolver class, the resolver method (`resolve_context_type`), the resolver purpose (`initial_context_resolution` or `pending_context_resolution`), the session id, the candidate_id, the candidate count, and the truncated intent JSON. The `Completed` event SHALL carry the call_id, the turn_id, the result type (`ContextType` or `None`), the resolved `ContextType`, the inferred `clarification_required`, the inferred `ready_for_execution`, and the original serialized `intent`. The function SHALL remain pure with respect to side effects: it SHALL NOT call `commit`, `rollback`, `flush`, or `begin`; it SHALL NOT modify the session model; it SHALL NOT call recognizers, handlers, or queue services. The function SHALL NOT re-classify or re-resolve the intent.

#### Scenario: Default sink is a no-op

- **WHEN** `resolve_context_type(intent)` is called without a `sink` argument
- **THEN** the function returns the same `ContextType | None` it returned before this subphase and emits no event

#### Scenario: Started event captures the intent input

- **WHEN** `resolve_context_type(intent, *, sink=stub)` is called with a `pending_resolution` intent whose `candidate_ids` is `[10, 11]`
- **THEN** the emitted `ResolverCallStarted` event carries `resolver_class="ContextTypeResolver"`, `resolver_method="resolve_context_type"`, `candidate_count=2`, and the serialized intent

#### Scenario: Completed event captures the resolved context type

- **WHEN** the function returns `ContextType.PRODUCT_SELECTION`
- **THEN** the emitted `ResolverCallCompleted` event carries `result_type="ContextType.PRODUCT_SELECTION"` and `resolved_context_type="PRODUCT_SELECTION"`

#### Scenario: Completed event captures None result

- **WHEN** the function returns `None`
- **THEN** the emitted `ResolverCallCompleted` event carries `result_type="None"` and `resolved_context_type=null`

#### Scenario: Resolver does not re-resolve when sink is active

- **WHEN** the same `resolve_context_type` is called with a `CollectingDiagnosticSink` and with a `NoopDiagnosticSink`
- **THEN** the underlying `PendingIntent` repository lookup and the `Requirement` walker run exactly once per call in both runs (no debug-induced re-resolution)
