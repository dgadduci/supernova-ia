## ADDED Requirements

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
transport, 429 and 5xx failures SHALL use bounded configured backoff; terminal
provider failures and exhausted retries SHALL NOT be silently resent.

#### Scenario: Accepted outbound delivery is not resent awaiting callback

- **WHEN** Twilio accepts an outbound row and returns a provider SID
- **THEN** the row becomes `accepted`
- **AND** a missing callback does not make the row eligible for another send

### Requirement: Twilio delivery callbacks are authenticated and monotonic

The system SHALL validate a Twilio status callback signature before any lookup
or mutation, and SHALL apply only monotonic delivery-state transitions to the
matching Twilio provider SID. Duplicate, stale or unknown valid callbacks SHALL
be idempotent no-ops.

#### Scenario: Invalid callback cannot alter delivery state

- **WHEN** a callback has a missing, malformed or invalid Twilio signature
- **THEN** the endpoint returns `403`
- **AND** it does not query or mutate an outbound provider-message row
