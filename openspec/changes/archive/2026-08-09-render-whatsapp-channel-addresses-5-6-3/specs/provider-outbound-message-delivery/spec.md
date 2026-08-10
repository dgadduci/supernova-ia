## ADDED Requirements

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
