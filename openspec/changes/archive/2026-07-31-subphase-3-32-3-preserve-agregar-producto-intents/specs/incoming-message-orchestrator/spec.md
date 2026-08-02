## ADDED Requirements

### Requirement: Incoming pending-context outcomes are propagated without loss
When a session has active context, `process_incoming_message` SHALL return the complete `list[ProcessedIntent]` from `dispatch_pending_context` unchanged rather than wrapping or truncating it.

#### Scenario: One reply produces multiple executed additions
- **WHEN** pending dispatch resolves and executes multiple preserved `agregar_producto` intents
- **THEN** the incoming-message orchestrator returns every result once and in the same order

#### Scenario: One unresolved result remains one result
- **WHEN** pending dispatch returns a one-item `pending_resolution` list
- **THEN** the incoming-message orchestrator returns that same one-item list unchanged

### Requirement: Transactional processing remains one transaction per message
Propagating multiple outcomes SHALL NOT add commits or rollbacks to the incoming-message orchestrator; the transactional wrapper SHALL still commit exactly once after successful processing and roll back exactly once after a raised exception.

#### Scenario: Multiple outcomes commit once
- **WHEN** one resolution message executes multiple queued additions successfully
- **THEN** transactional processing commits once after all outcomes are produced
