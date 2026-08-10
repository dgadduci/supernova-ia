## ADDED Requirements

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
