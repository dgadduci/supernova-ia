# Capability: context-type-resolver

## Purpose

Define a single pure function that maps a `ProcessedIntent` to a `ContextType` enum (or `None`) based purely on the intent's status, requirements, and candidate_ids — exposing only the resolver function itself (no recognizer call, no handler invocation, no `PendingIntentService` call, no session mutation, no persistence, no schema change, no router, no endpoint) so other modules can determine whether product selection is needed without triggering any side effects.

## Requirements

### Requirement: ContextTypeResolver function exists
The system SHALL export a single function `resolve_context_type(intent: ProcessedIntent) -> ContextType | None` from `backend.intents.context.context_type_resolver`. The function SHALL be pure: no I/O, no DB, no recognizer call, no handler invocation, no session mutation, no persistence.

#### Scenario: Function is importable
- **WHEN** any module executes `from backend.intents.context.context_type_resolver import resolve_context_type`
- **THEN** the import completes without raising and the binding is a callable

### Requirement: Pending product selection returns PRODUCT_SELECTION
The function SHALL return `ContextType.PRODUCT_SELECTION` when **all three** conditions hold:
1. `intent.status == "pending_resolution"`
2. requirement `producto_presentacion_id` exists with `status == "pending"`
3. `intent.candidate_ids` is non-empty

#### Scenario: All three conditions met
- **WHEN** the test calls `resolve_context_type` on a `ProcessedIntent` with `status="pending_resolution"`, a `RequirementState(name="producto_presentacion_id", status="pending", value=None)` in `requirements`, and `candidate_ids=[10, 11]`
- **THEN** the result is `ContextType.PRODUCT_SELECTION`

#### Scenario: Single candidate still returns PRODUCT_SELECTION
- **WHEN** the test calls `resolve_context_type` on an intent with `candidate_ids=[42]`
- **THEN** the result is `ContextType.PRODUCT_SELECTION`

#### Scenario: Two pending requirements still returns PRODUCT_SELECTION
- **WHEN** the test calls `resolve_context_type` on an intent with `requirements=[RequirementState("producto_presentacion_id", "pending", None), RequirementState("cantidad", "pending", 1)]` and `candidate_ids=[1]`
- **THEN** the result is `ContextType.PRODUCT_SELECTION` (the function only checks `producto_presentacion_id`; other requirements are ignored)

### Requirement: Missing candidates returns None
The function SHALL return `None` when the intent is otherwise valid for product selection but `candidate_ids` is empty.

#### Scenario: Empty candidate_ids returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="pending_resolution"`, the `producto_presentacion_id` requirement is `pending`, and `candidate_ids=[]`
- **THEN** the result is `None`

#### Scenario: Missing candidate_ids key returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="pending_resolution"`, the `producto_presentacion_id` requirement is `pending`, and `candidate_ids=[]` (empty list, the natural default)
- **THEN** the result is `None`

### Requirement: Non-pending intent returns None
The function SHALL return `None` when `intent.status` is not `"pending_resolution"`, regardless of the requirements and candidate_ids.

#### Scenario: ready status returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="ready"`, the `producto_presentacion_id` requirement is `completed`, and `candidate_ids=[1]`
- **THEN** the result is `None`

#### Scenario: executed status returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="executed"`
- **THEN** the result is `None`

#### Scenario: rejected status returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="rejected"`
- **THEN** the result is `None`

#### Scenario: failed status returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="failed"`
- **THEN** the result is `None`

### Requirement: Unrelated pending requirement returns None
The function SHALL return `None` when the intent is `pending_resolution` and has `candidate_ids` but the `producto_presentacion_id` requirement is either missing or not `pending`.

#### Scenario: Missing producto_presentacion_id requirement returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="pending_resolution"`, no `producto_presentacion_id` requirement in `requirements`, and `candidate_ids=[1]`
- **THEN** the result is `None`

#### Scenario: Empty requirements list returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="pending_resolution"`, `requirements=[]`, and `candidate_ids=[1]`
- **THEN** the result is `None`

#### Scenario: producto_presentacion_id completed returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="pending_resolution"`, `requirements=[RequirementState("producto_presentacion_id", "completed", 42)]`, and `candidate_ids=[1]`
- **THEN** the result is `None`

#### Scenario: Only a different pending requirement returns None
- **WHEN** the test calls `resolve_context_type` on an intent with `status="pending_resolution"`, `requirements=[RequirementState("cantidad", "pending", 1)]`, and `candidate_ids=[1]`
- **THEN** the result is `None`

### Requirement: Module is importable without side effects
The system SHALL make `resolve_context_type` importable from `backend.intents.context.context_type_resolver` without side effects, errors, or required dependencies beyond the standard library, Pydantic, and the existing Phase 3 modules.

#### Scenario: Import succeeds and the symbol is present
- **WHEN** any module executes `from backend.intents.context.context_type_resolver import resolve_context_type`
- **THEN** the import completes without raising and the binding is the function

### Requirement: No additional implementation
The subphase SHALL NOT introduce a recognizer call, a handler invocation, a `PendingIntentService` call, a session mutation, persistence, a model change, a migration, a router, a FastAPI endpoint, or any other intent-related runtime code. The only new code is the resolver function, the empty `__init__.py`, and the verification test.

#### Scenario: Only the resolver module is added
- **WHEN** the test lists non-`__init__.py` files under `backend/intents/context/`
- **THEN** the file set is exactly `{"context_type_resolver.py"}`

#### Scenario: Only the one public symbol is exported
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"resolve_context_type"}`

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
