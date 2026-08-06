# Capability: twilio-inbound-webhook

## ADDED Requirements

### Requirement: Twilio inbound requests are validated before routing

The system SHALL accept a Twilio WhatsApp inbound form request only after its
signature is validated against the configured public webhook URL, submitted
form parameters and `X-Twilio-Signature`. Invalid or unavailable validation
configuration SHALL fail closed before any database, routing or processing
operation.

#### Scenario: Invalid signature has no side effects

- **WHEN** the signature is missing, malformed or invalid for the public URL
  and submitted form values
- **THEN** the endpoint returns `403`
- **AND** it does not resolve a client/channel, claim a receipt or invoke the
  provider-message coordinator

### Requirement: Valid dedicated Twilio messages delegate to the common core

For a valid request with non-empty `MessageSid`, `From`, `To` and `Body`, the
system SHALL resolve an existing active client from `From` and an active
dedicated channel from `To`, then submit exactly that routing decision to the
Phase-5.4 provider-message coordinator with provider `twilio` and receipt id
`MessageSid`.

#### Scenario: First dedicated delivery is processed once

- **WHEN** a valid signed message targets an active dedicated channel and an
  existing active client
- **THEN** the endpoint delegates one command containing the resolved channel,
  client and exclusive commerce ids to the common coordinator
- **AND** it returns `200` acknowledgement TwiML only after the coordinator
  reports `processed`

#### Scenario: Shared destination does not select a commerce

- **WHEN** a valid signed message targets an active shared channel
- **THEN** the endpoint returns safe control TwiML
- **AND** it does not invoke the coordinator or mutate shared selection state

### Requirement: TwiML does not create an outbound replay contract

The system SHALL return empty TwiML for an `already_processed` receipt and a
safe generic control TwiML for non-processing business outcomes. It SHALL NOT
persist a TwiML response, replay a prior response, or convert technical
failures into a duplicate/business outcome.

#### Scenario: Duplicate delivery has no response replay

- **WHEN** the common coordinator reports `already_processed` for a valid
  signed receipt
- **THEN** the endpoint returns `200` with an empty TwiML response
- **AND** it does not invoke a response builder, delivery client or pipeline
