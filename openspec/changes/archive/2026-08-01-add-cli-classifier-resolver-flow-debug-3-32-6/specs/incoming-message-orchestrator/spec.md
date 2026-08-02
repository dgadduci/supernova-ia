## ADDED Requirements

### Requirement: Incoming-message orchestrator accepts a diagnostic sink

The `process_incoming_message` function SHALL accept an optional `sink: DiagnosticSink` keyword argument that defaults to `NoopDiagnosticSink()`. The function SHALL pass the sink through to the classifier call, the initial dispatcher, the pending-context dispatcher, and every resolver reachable through the dispatch path. The function SHALL NOT treat the sink as a return value; it SHALL NOT change the existing `list[ProcessedIntent]` return contract. The function SHALL NOT commit, rollback, flush, or perform any persistence operation. The function SHALL NOT change the dispatching behavior, the message validation, the pending-context routing, the initial routing, or the result wrapping.

#### Scenario: Default sink is a no-op

- **WHEN** `process_incoming_message(db, session, message)` is called without a `sink` argument
- **THEN** the orchestrator runs the same dispatch path as before, returns the same `list[ProcessedIntent]`, and emits no event

#### Scenario: Injected sink is propagated

- **WHEN** `process_incoming_message(db, session, message, *, sink=stub_sink)` is called
- **THEN** the stub sink receives the classifier events and the resolver events emitted by the dispatch path, and the orchestrator still returns the same `list[ProcessedIntent]`

#### Scenario: Orchestrator does not commit or rollback

- **WHEN** `process_incoming_message(db, session, message, *, sink=stub_sink)` completes for any routing branch
- **THEN** `db.commit` and `db.rollback` have not been called by the orchestrator module

### Requirement: Incoming-message orchestrator returns the sink's collected events

The `process_incoming_message` function SHALL NOT return the sink's events through its return value. The events are returned to the caller through the sink itself (`sink.events()`) and emitted by the FastAPI router as a `diagnostics` field on the response payload. The function's return contract SHALL remain `list[ProcessedIntent]`.

#### Scenario: Return type is unchanged

- **WHEN** `process_incoming_message(db, session, message, *, sink=stub_sink)` is called with a sink that recorded events
- **THEN** the function returns a `list[ProcessedIntent]` (not a tuple, not a dict, not a `ProcessResult`) and the events are accessible through `sink.events()`

#### Scenario: Sink events are independent of the return value

- **WHEN** the orchestrator returns a `list[ProcessedIntent]` from the dispatch path
- **THEN** the same `list[ProcessedIntent]` is returned when the sink is a `NoopDiagnosticSink`, a `CollectingDiagnosticSink`, or any custom `DiagnosticSink` implementation
