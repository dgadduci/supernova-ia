## MODIFIED Requirements

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
