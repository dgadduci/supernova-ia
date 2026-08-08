## MODIFIED Requirements

### Requirement: Dispatch is lease-protected and retry-bounded

The system SHALL dispatch only one due leased outbound row at a time and SHALL
record a Twilio acceptance SID before accepting callback updates. Retryable
transport failures and real Twilio REST API responses with HTTP `429`, `408`,
`425` or `5xx` statuses SHALL use bounded configured backoff. Terminal Twilio
REST API responses with other HTTP statuses, and exhausted retries, SHALL NOT
be silently resent.

The Twilio adapter SHALL translate the pinned SDK's `TwilioRestException` into
these typed outcomes using its HTTP `status`, not its provider error `code`.
Unknown programming/configuration exceptions SHALL remain technical failures
and SHALL NOT be silently classified as provider outcomes.

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
