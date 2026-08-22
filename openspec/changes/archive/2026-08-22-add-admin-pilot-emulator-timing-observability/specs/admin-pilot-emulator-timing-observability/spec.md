# Capability: Admin/Pilot Emulator timing observability

## ADDED Requirements

### Requirement: The Emulator conversation SHALL display bounded observation timestamps

The Admin/Pilot Emulator conversation SHALL display a local browser timestamp
formatted as `HH:MM:SS.mmm` beside each `Enviado`, `Estado`, `Respuesta
recibida` and `Error` row. The timestamp SHALL identify when the panel
rendered or observed that row and SHALL NOT be represented as a server
transition time.

#### Scenario: Sent and status rows show local observation times

- **WHEN** the operator submits a non-empty Emulator message and the panel
  observes an accepted or pending status
- **THEN** the conversation shows one `Enviado` row and one status row
- **AND THEN** each row shows a bounded `HH:MM:SS.mmm` local timestamp
- **AND THEN** repeated polling updates the existing status row without
  duplicating the turn

#### Scenario: Response and error rows show local observation times

- **WHEN** the panel observes an outbound response or a retryable, terminal or
  generic error outcome
- **THEN** it shows the existing response or error row with a local
  `HH:MM:SS.mmm` observation timestamp
- **AND THEN** it does not replace or remove the original `Enviado` row

### Requirement: The status projection SHALL expose an exact bounded timing timeline

The existing Emulator status endpoint SHALL return a nullable, closed `timeline`
object for the exact selected pedido/session/comercio and
`synthetic_inbound_id`. The timeline MAY contain only inbound receipt time,
LLM request time, LLM completion/failure time, LLM outcome, processing
finalization time and response-staging time. Server timestamps SHALL be
UTC ISO-8601 strings; unavailable milestones SHALL be `null`.

#### Scenario: Accepted work has partial timeline data

- **WHEN** the exact synthetic inbound receipt exists but the worker has not
  started the LLM request
- **THEN** the endpoint returns the existing accepted or pending status
- **AND THEN** `inbound_received_at` is populated
- **AND THEN** LLM, processing and response-staging fields remain `null`

#### Scenario: A cross-target timeline is not exposed

- **WHEN** the operator polls with a synthetic inbound identifier belonging to
  another pedido, session or comercio
- **THEN** the endpoint returns its existing bounded rejection behavior
- **AND THEN** it does not return the other target's timeline, response body,
  provider SID or status

### Requirement: The provider worker SHALL record safe LLM request and completion timing

For the provider inbound processing path, the system SHALL record the time at
which the existing worker requests the LLM and the time at which that request
completes normally or finishes with a timeout/error. It SHALL record a closed
outcome of `completed`, `timeout` or `error` and SHALL correlate the
observability event with the opaque synthetic inbound identifier when one is
available. It SHALL NOT record prompt text, LLM response text, customer text,
PII, secrets, signatures or raw exception messages.

#### Scenario: LLM responds normally

- **WHEN** the provider worker receives a normal LLM response for an accepted
  inbound message
- **THEN** the processing timeline contains both LLM request and completion
  timestamps
- **AND THEN** the LLM outcome is `completed`
- **AND THEN** existing business processing, outbox creation and response
  behavior remain unchanged

#### Scenario: LLM times out

- **WHEN** the existing LLM request reaches its configured timeout
- **THEN** the processing timeline records the request timestamp, the timeout
  completion timestamp and outcome `timeout`
- **AND THEN** the existing retry or terminal finalization behavior remains
  authoritative
- **AND THEN** the panel can distinguish the timeout from a Twilio Emulator
  transport rejection without exposing exception details

### Requirement: Timing observability SHALL preserve privacy and existing behavior

The timing feature SHALL be additive and fail non-blocking. Missing,
malformed or unavailable timing data SHALL never trigger a retry, fallback,
second LLM request, status change or rejection. Existing Emulator status
values, T-C routing, Twilio Emulator behavior, transaction ownership and
polling behavior SHALL remain unchanged.

#### Scenario: Timeline data is unavailable

- **WHEN** an older row or an unavailable milestone has no timing value
- **THEN** the status and existing response/error behavior remain available
- **AND THEN** the panel renders `—` for the missing server value
- **AND THEN** no provider or worker behavior changes

#### Scenario: Timing fields remain safe

- **WHEN** a timeline is returned or an LLM event is emitted
- **THEN** only bounded timestamps, the closed outcome and the safe opaque
  correlation identifier are present
- **AND THEN** prompts, LLM response bodies, customer text, phone numbers,
  provider payloads, credentials, signatures and raw exception text are absent

### Requirement: Timing persistence SHALL respect existing transaction ownership

Timing metadata SHALL be written through the existing provider coordinator and
worker lease/finalization transaction. A business rollback caused by a
technical failure SHALL NOT silently erase the timing needed to diagnose the
attempt; the existing retry or terminal finalization path SHALL retain the
safe metadata without an independent observability transaction.

#### Scenario: Retry retains a failed LLM timing attempt

- **WHEN** the worker rolls back business effects after an LLM timeout and
  schedules the existing retry
- **THEN** the retryable work item retains its LLM request time, completion
  time and closed timeout outcome
- **AND THEN** no receipt, session, order or outbox transaction semantics
  change
