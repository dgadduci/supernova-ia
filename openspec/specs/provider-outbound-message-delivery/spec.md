# Capability: provider-outbound-message-delivery

## Purpose

TBD: Provide the Phase-5.6 outbound counterpart to `provider-message-receipt-core`, defining the transaction-owning staging, lease-protected dispatch and authenticated Twilio status-callback boundary for outbound provider messages.
## Requirements
### Requirement: First provider processing persists ordered outbound work

The system SHALL stage one ordered durable outbound provider-message row for
each customer response produced by a first valid Phase-5.4 inbound receipt.
The rows, receipt, compatible session and pipeline effects SHALL commit in the
same transaction. A duplicate receipt SHALL create no outbound row and SHALL
NOT rebuild or replay a customer response.

#### Scenario: Rollback leaves no sendable response

- **WHEN** response staging or pipeline processing fails before the Phase-5.4
  commit
- **THEN** no outbound row, receipt claim, staged session or pipeline effect is
  durable

### Requirement: Dispatch is lease-protected and retry-bounded

The system SHALL dispatch only one due leased outbound row at a time and SHALL
record a Twilio acceptance SID before accepting callback updates. Retryable
transport failures and real Twilio REST API responses with HTTP `429`, `408`,
`425` or `5xx` SHALL use bounded configured backoff. Terminal Twilio REST
responses with other HTTP statuses, and exhausted retries, SHALL NOT be
silently resent.

For every completed claimed-row attempt, the dispatcher SHALL emit one
sanitized outbound-attempt record with outcome, outbox id, and only applicable
safe fields: attempt count, durable state, failure category, provider error
code, HTTP status or technical exception class. The automatic worker SHALL
emit safe outcome/category aggregates per completed cycle. Neither record SHALL
contain bodies, E.164 values, provider payloads/URLs, signatures, credentials,
account identifiers, exception messages or tracebacks.

The Twilio adapter SHALL translate the pinned SDK's `TwilioRestException`
using its HTTP `status`; provider error code is captured as safe diagnostic
metadata and SHALL NOT change retry policy without an explicitly approved
requirement. Unknown programming/configuration exceptions SHALL remain
technical failures and SHALL NOT be silently classified as provider outcomes.

#### Scenario: Real Twilio REST rejection is finalized safely

- **WHEN** the real Twilio SDK raises `TwilioRestException` for a claimed row
- **THEN** the adapter produces a typed retryable or terminal result according
  to the exception HTTP status
- **AND** the dispatcher conditionally finalizes the row using its lease token
- **AND** no raw exception content reaches persisted state or CLI output

#### Scenario: Unexpected adapter error is not misclassified

- **WHEN** the SDK seam raises a `TypeError` or an exception outside the
  explicit transport/REST categories
- **THEN** the error remains a technical dispatch failure
- **AND** the adapter does not convert it into a retryable or terminal
  provider outcome

#### Scenario: Accepted outbound delivery is not resent awaiting callback

- **WHEN** Twilio accepts an outbound row and returns a provider SID
- **THEN** the row becomes `accepted`
- **AND** a missing callback does not make the row eligible for another send

#### Scenario: A terminal Twilio rejection is visible without replay

- **WHEN** a claimed row receives a classified terminal Twilio REST rejection
- **THEN** the dispatcher conditionally finalizes the row using its lease token
- **AND** exactly one safe terminal attempt record contains its outbox id,
  attempt count, category, code and HTTP status when known
- **AND** the worker cycle exposes a safe terminal aggregate
- **AND** the system does not rerun inbound work, rebuild a response, mutate an
  order, or send through another channel

#### Scenario: A technical dispatch failure remains diagnosable and unclassified

- **WHEN** the SDK seam raises an unexpected programming/configuration error
- **THEN** the failure remains technical and the safe record identifies only
  the exception class
- **AND** the dispatcher does not fabricate a provider result or log raw
  exception text

### Requirement: Twilio delivery callbacks are authenticated and monotonic

The system SHALL validate a Twilio status callback signature before any lookup
or mutation, and SHALL apply only monotonic delivery-state transitions to the
matching Twilio provider SID. Duplicate, stale or unknown valid callbacks SHALL
be idempotent no-ops.

#### Scenario: Invalid callback cannot alter delivery state

- **WHEN** a callback has a missing, malformed or invalid Twilio signature
- **THEN** the endpoint returns `403`
- **AND** it does not query or mutate an outbound provider-message row

### Requirement: Twilio create call uses only the supported Message-create contract

The Twilio outbound adapter SHALL call the pinned Twilio SDK Message-create
seam using only the supported `to`, `from_`, `body` and `status_callback`
keyword arguments. It SHALL NOT pass the internal outbox idempotency key, or
any other unsupported keyword, to the provider SDK.

The durable lease and conditional finalization remain the system's local
idempotency/concurrency boundary; absence of a provider idempotency argument
SHALL NOT cause an inbound replay, a rebuilt customer response, a TwiML
fallback or a send through another channel.

#### Scenario: Strict SDK-compatible seam accepts a normal outbound send

- **WHEN** the dispatcher sends a claimed row through a Message-create seam
  that accepts only `to`, `from_`, `body` and `status_callback`
- **THEN** the adapter calls the seam exactly once with those four arguments
- **AND** a returned provider SID follows the existing conditional
  `accepted` finalization path

#### Scenario: Internal key never crosses the provider boundary

- **WHEN** a claimed row has an internal deterministic outbox idempotency key
- **THEN** the key remains internal to the dispatch boundary
- **AND** it is not passed to the Twilio SDK Message-create call

### Requirement: WhatsApp outbound addresses are rendered at the provider edge

The Twilio outbound adapter SHALL preserve canonical bare E.164 values inside
the application and SHALL render the sender and recipient as `whatsapp:+E.164`
channel addresses only when invoking the Twilio Message-create SDK seam.

It SHALL pass no duplicate channel prefix and SHALL NOT alter persisted outbox
destinations, sender configuration, routing values or inbound normalization.

#### Scenario: Canonical outbox row sends through WhatsApp channel

- **WHEN** a claimed Twilio outbound row contains a canonical E.164 recipient
  and the configured sender is canonical E.164
- **THEN** the adapter calls the SDK with both `to` and `from_` prefixed by
  `whatsapp:`
- **AND** the SDK call retains only its supported `to`, `from_`, `body` and
  `status_callback` arguments

#### Scenario: Provider address rendering does not change local outbox state

- **WHEN** the adapter renders WhatsApp channel addresses for a send attempt
- **THEN** the stored recipient and configured sender remain canonical E.164
- **AND** existing lease-conditional accepted/retry/terminal finalization
  behavior remains unchanged
