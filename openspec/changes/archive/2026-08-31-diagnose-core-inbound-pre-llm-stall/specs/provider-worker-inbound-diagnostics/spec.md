# Capability: provider-worker-inbound-diagnostics

## ADDED Requirements

### Requirement: Core inbound checkpoints distinguish pre-LLM boundaries

The leased provider inbound path SHALL emit a privacy-safe
`provider_inbound_checkpoint` event after each of the following existing
operations returns: availability evaluation, active-session loading, draft
staging decision, session-order flush, and business-dispatch selection. Each
event SHALL use a closed checkpoint token, the existing opaque provider
correlation value and only the bounded fields allowed for that checkpoint.

The diagnostic SHALL preserve the existing `provider_inbound_stage` events for
stage entry/exit and the existing `llm_request` events for the actual LLM
boundary. It SHALL NOT perform transaction control, change a business result,
or create a recovery path.

#### Scenario: Available turn exposes the pre-LLM sequence

- **WHEN** a leased turn passes availability, loads its active session,
  evaluates/stages its draft pedido, flushes session/order state and enters
  the existing business dispatcher
- **THEN** the event stream contains, in order, `availability_evaluated`,
  `session_loaded`, `draft_stage_decision`, `session_order_flushed` and
  `business_dispatch_started`
- **AND THEN** the existing stage events and subsequent `llm_request` event
  retain their current behavior and correlation

#### Scenario: Availability result is bounded

- **WHEN** availability evaluation returns
- **THEN** `availability_evaluated` records only `available` or `unavailable`
- **AND THEN** an unavailable result may record only
  `blocked_state`, `trial_expired` or `trial_quota_exhausted`
- **AND THEN** no commerce ID, status label, trial date, quota, message or
  exception text is emitted

#### Scenario: Session and draft state are distinguishable without IDs

- **WHEN** the session/order staging sequence returns
- **THEN** `session_loaded`, `draft_stage_decision` and
  `session_order_flushed` expose only their allowed boolean fields
- **AND THEN** an existing draft and a draft created for the turn are
  distinguishable without exposing session, pedido, client or commerce IDs
- **AND THEN** the existing flush and transaction ownership are unchanged

#### Scenario: Dispatch branch is visible before business work

- **WHEN** the existing business pipeline is about to invoke its dispatcher
- **THEN** `business_dispatch_started` records exactly one of `initial`,
  `pending_context` or `unsupported`
- **AND THEN** a missing later `llm_request` can be interpreted as work inside
  the selected branch before the classifier LLM boundary
- **AND THEN** no dispatcher, classifier, prompt, response or context payload
  is duplicated or included in the event

#### Scenario: Partial trace remains honest

- **WHEN** an operation blocks, times out or raises before a later checkpoint
  is emitted
- **THEN** only checkpoints reached after a successful return are present
- **AND THEN** existing stage `started`, `llm_request`, processing timing and
  durable outcome events remain authoritative evidence
- **AND THEN** the system does not fabricate completion, relabel a timeout,
  release a lease, schedule a retry or replay the message from missing
  checkpoint evidence

#### Scenario: Diagnostic emission is fail-soft

- **WHEN** checkpoint validation or emission fails
- **THEN** the existing provider processing call continues with its original
  business result and failure semantics
- **AND THEN** no commit, rollback, flush, side session, fallback response or
  rejected payload is produced by the diagnostic
