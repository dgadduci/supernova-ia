# Capability: provider-emulator-outbound-diagnostics

## ADDED Requirements

### Requirement: Provider processing outcome exposes the outbound staging boundary

The provider coordinator SHALL emit one privacy-safe structured
`provider_inbound_processing_outcome` event after the existing authoritative
processing result is known. The event SHALL distinguish
`processed_with_response` from `processed_without_response` using the existing
mapper result and durable outbox staging count. It SHALL also use closed
outcomes for `retry_scheduled`, `failed_terminal`, `lease_lost` and
`unavailable` when those existing finalization paths occur.

The event SHALL contain only bounded response/outbox counts, the existing safe
failure category when applicable and an opaque bounded correlation value when
already authorized by the provider timing contract. It SHALL NOT contain
message text, phone numbers, provider identifiers or payloads, prompts, model
output, URLs, credentials, secrets, raw exception text or tracebacks.

#### Scenario: Processed response reaches outbound staging

- **WHEN** the existing deferred processor commits one or more mapped customer
  responses and their outbound rows
- **THEN** it emits exactly one `processed_with_response` diagnostic with
  matching bounded response and outbox counts
- **AND THEN** it preserves the existing processing commit and does not invoke
  any additional mapper, worker, dispatcher or provider path

#### Scenario: Processed turn stages no outbound response

- **WHEN** the existing deferred processor commits `processed` and the mapper
  returns zero staged outbound rows
- **THEN** it emits exactly one `processed_without_response` diagnostic with
  zero bounded counts
- **AND THEN** it does not create a fallback response, retry the inbound,
  invoke the outbound dispatcher or contact T-C

#### Scenario: Diagnostic emission cannot change business processing

- **WHEN** event validation, serialization or writing fails after the existing
  processing result is known
- **THEN** the existing commit, retry, lease and finalization behavior remains
  unchanged
- **AND THEN** no raw event payload or exception text is printed as a fallback

### Requirement: Emulator status exposes an exact bounded processing diagnostic

The Admin/Pilot Emulator status response SHALL retain its existing status and
timing fields and SHALL add a closed diagnostic projection scoped to the exact
selected pedido, session, commerce and synthetic inbound identifier. The
diagnostic SHALL expose only a closed processing state, nullable bounded
response/outbox counts and a nullable existing closed failure category.

The projection SHALL derive `processed_without_response` only when the exact
processing row is durably `processed` and zero outbox rows are linked to the
exact receipt. A missing processing row SHALL NOT be treated as a completed
zero-response turn. The route SHALL remain read-only and SHALL never process,
repair, retry or dispatch the turn.

#### Scenario: Exact processed-without-response state is visible

- **WHEN** the selected synthetic inbound has an exact durable processing row
  in `processed` state and no receipt-linked outbound rows
- **THEN** the status response retains `status=processed` and exposes the
  closed diagnostic state `processed_without_response` with zero counts
- **AND THEN** it returns no body, provider SID, message text or raw failure
  detail

#### Scenario: A normal response remains distinguishable

- **WHEN** the exact synthetic inbound has one or more receipt-linked
  outbound rows
- **THEN** the status response exposes `processed_with_response` and the
  bounded counts while preserving the existing body/SID projection and timing
  timeline

#### Scenario: Cross-target data cannot enter the diagnostic

- **WHEN** the status request targets a different pedido/session/commerce or a
  synthetic inbound identifier not belonging to the selected target
- **THEN** the route returns its existing generic rejection or empty exact
  projection according to the current contract
- **AND THEN** it does not expose processing or outbox data from another turn

### Requirement: The Admin/Pilot panel does not mislabel diagnostic polling outcomes

The Admin/Pilot browser SHALL stop polling when the status projection reports
the definitive `processed_without_response` diagnostic. It SHALL show a
neutral bounded message that processing completed without an outbound
response, preserve the server timing timeline and conversation history, and
release the form for another test.

Polling HTTP errors, malformed status payloads and exhausted polling SHALL use
a neutral status-query failure message. They SHALL NOT claim that the Twilio
Emulator rejected the message. Actual bounded `retryable` and `terminal`
outbound states SHALL remain visible as their existing state.

#### Scenario: Zero-response processing ends the polling loop

- **WHEN** polling receives `status=processed` with diagnostic state
  `processed_without_response`
- **THEN** the panel appends a bounded status diagnostic, stops polling and
  enables the form
- **AND THEN** it does not append an emulator-rejected error row

#### Scenario: Polling timeout remains neutral

- **WHEN** the status endpoint cannot be read, returns an invalid payload or
  does not reach a terminal diagnostic before the attempt bound
- **THEN** the panel displays a neutral status-query failure
- **AND THEN** it does not assert that T-C or the Twilio Emulator rejected the
  message

#### Scenario: Successful response behavior remains unchanged

- **WHEN** the exact status reaches `processed` or `sent` with a bounded
  outbound body
- **THEN** the panel renders the received response, existing timing fields and
  conversation row as before
- **AND THEN** the new diagnostic does not cause a second poll, send or LLM
  request
