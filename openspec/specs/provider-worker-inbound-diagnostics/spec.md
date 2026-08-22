# Capability: provider-worker-inbound-diagnostics

## Purpose

Make the leased provider inbound processing path diagnosable at its bounded
seams (stage entry/exit, model-request correlation and durable outcome) by
emitting privacy-safe, non-replaying diagnostic events around the existing
coordinator flow. The diagnostic SHALL refine, but never replace, the
authoritative durable outcome, transaction ownership and existing failure
policy.

## Requirements

### Requirement: Deferred provider processing exposes bounded stage evidence

The leased provider inbound coordinator SHALL emit a privacy-safe
`provider_inbound_stage` event for each bounded stage it enters:
`availability`, `session_order`, `business_pipeline`, `outbound_staging` and
`processing_finalization`. It SHALL emit `started` before entering the stage,
and SHALL emit `completed` or `failed` only after the existing stage returns.

The event SHALL contain only the closed stage and outcome, a bounded elapsed
duration when the stage returns, a safe exception type when the stage fails,
and the existing opaque provider correlation value. It SHALL NOT contain
message text, prompts, model output, vectors, phone numbers, database IDs,
provider identifiers, URLs, credentials, secrets, raw exception text or
tracebacks.

#### Scenario: Successful inbound stage sequence is observable

- **WHEN** a leased provider receipt reaches the existing availability,
  session/order, business pipeline, outbound staging and finalization seams
- **THEN** each entered stage emits one `started` event before the seam and one
  `completed` event after the seam returns
- **AND THEN** the event order reflects the existing coordinator order
- **AND THEN** the business result, transaction ownership and outbound path are
  unchanged

#### Scenario: Stage failure remains under the existing failure policy

- **WHEN** an instrumented stage raises a technical exception
- **THEN** that stage emits one bounded `failed` event with only its safe
  exception type
- **AND THEN** the existing rollback, lease, retry or terminal finalization
  path remains authoritative
- **AND THEN** no fallback response, replay, dispatcher call or recovery is
  introduced by the diagnostic

#### Scenario: Incomplete stage is not given a fabricated result

- **WHEN** the worker emits a stage `started` event and the existing stage has
  not returned
- **THEN** no synthetic `completed`, `failed`, processing outcome or lease
  repair is emitted for that stage
- **AND THEN** the worker retains its existing supervisor and transaction
  behavior

#### Scenario: Diagnostic emission failure is fail-soft

- **WHEN** validation, correlation setup or serialization of a diagnostic
  event fails
- **THEN** the existing provider processing call continues with its original
  business result and failure semantics
- **AND THEN** no rejected payload, prompt, body or exception message is
  printed as a fallback

### Requirement: Provider model requests are correlated without content

When generation or semantic embedding is reached from a leased provider
inbound turn, the corresponding `llm_request` or `embedding_request` event
SHALL carry the same bounded opaque correlation value as the provider stage
events. The generation and embedding events SHALL remain distinguishable by
their existing event/component contracts. Direct non-provider client calls
SHALL not inherit a stale provider correlation value.

#### Scenario: Intent-classifier generation is linked to its turn

- **WHEN** the existing provider business pipeline invokes the intent
  classifier's `QueryLlm` boundary
- **THEN** its existing `llm_request` events carry the exact provider-scoped
  correlation value
- **AND THEN** no prompt, customer text, model response or URL is added

#### Scenario: Semantic embedding is linked to its turn

- **WHEN** the existing provider business pipeline invokes the Ollama semantic
  embedding boundary
- **THEN** its existing `embedding_request` events carry the same provider-
  scoped correlation value
- **AND THEN** the event contains no input text, vector values, provider URL or
  secret

#### Scenario: Correlation context is cleared after the turn

- **WHEN** provider processing completes, rolls back, retries, reaches terminal
  failure, becomes unavailable or loses its lease
- **THEN** the provider correlation context is cleared
- **AND THEN** a later direct or unrelated client call emits no stale provider
  correlation value

### Requirement: Durable processing outcomes remain authoritative

The new diagnostic SHALL refine, but never replace, the existing
`provider_inbound_processing_outcome`, provider-worker-liveness and Emulator
timeline contracts. A diagnostic event SHALL NOT be interpreted as a durable
business state, and the status route SHALL remain read-only.

#### Scenario: Processed outcome remains the source of truth

- **WHEN** the coordinator commits a processed turn with or without staged
  outbound rows
- **THEN** the existing `processed_with_response` or
  `processed_without_response` event remains authoritative
- **AND THEN** stage evidence does not create a second finalization or outbound
  attempt

#### Scenario: Missing completion evidence identifies an investigation point

- **WHEN** logs contain a provider stage or model-request `started` event but
  no matching completion/failure event
- **THEN** operators can identify the last reached boundary for that opaque
  turn
- **AND THEN** the system does not claim success, invent a timeout, or trigger
  automatic recovery from the missing event alone