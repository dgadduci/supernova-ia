# Capability: admin-pilot-emulator-status-integrity

## ADDED Requirements

### Requirement: Emulator status reflects the exact durable state when no outbound row exists

The Admin/Pilot Emulator status projection SHALL derive its wire `status`
from the closed diagnostic state for the exact selected receipt when no
receipt-linked outbound row exists. It SHALL never report `processed` merely
because the outbox count is zero.

#### Scenario: Pending or leased work remains pending

- **WHEN** the exact receipt has no outbox rows and its processing diagnostic
  is `not_started`, `pending`, `leased` or `unknown`
- **THEN** the status response returns `status=pending`
- **AND THEN** it does not return a body, provider SID or a successful
  processed state
- **AND THEN** the browser remains eligible to poll for a later terminal
  state

#### Scenario: Processed without response remains definitive

- **WHEN** the exact processing row is durably `processed` and no outbound
  row is linked to the exact receipt
- **THEN** the status response returns `status=processed` with diagnostic
  `processed_without_response`
- **AND THEN** the browser may finish with its neutral processed-without-
  response message

#### Scenario: Retryable and terminal states remain visible

- **WHEN** the exact processing row is `retryable` or `failed_terminal` and
  no outbound row exists
- **THEN** the response returns the corresponding closed `retryable` or
  `terminal` status
- **AND THEN** it does not label the turn as processed or as an Emulator
  transport rejection

#### Scenario: Missing receipt keeps the existing accepted projection

- **WHEN** the exact synthetic inbound receipt does not yet exist
- **THEN** the response retains `status=accepted` and the existing empty
  diagnostic/timeline projection
- **AND THEN** the route does not infer state from another receipt, order,
  session or commerce

#### Scenario: Exact-target isolation remains enforced

- **WHEN** a status request references a synthetic inbound identifier that
  belongs to another selected target
- **THEN** the existing generic rejection or empty exact projection is
  returned according to the current contract
- **AND THEN** no processing or outbox state from the other target enters the
  response

### Requirement: The browser does not convert pending status into an Emulator rejection

The Admin/Pilot browser SHALL keep polling a valid `pending` status within
the existing attempt bound. It SHALL reserve the generic Emulator rejection
message for the existing explicit submit/transport rejection path and use the
existing neutral polling message when the status query is exhausted or
malformed.

#### Scenario: Pending polling continues neutrally

- **WHEN** a valid status response reports `status=pending`
- **THEN** the browser appends/updates the bounded pending status and polls
  again while attempts remain
- **AND THEN** it does not append an Emulator rejection error

#### Scenario: Polling exhaustion remains neutral

- **WHEN** pending status never reaches a definitive state before the attempt
  bound
- **THEN** the browser stops polling and shows the existing neutral
  status-query failure
- **AND THEN** it does not claim that T-C or the Twilio Emulator rejected the
  message
