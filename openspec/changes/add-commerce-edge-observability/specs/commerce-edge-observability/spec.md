## ADDED Requirements

### Requirement: Isolated inbound business outcomes are emitted as closed structured events

The T-C adapter SHALL emit exactly one
`commerce_installation_inbound_outcome` JSON event after each local webhook
outcome is determined. NovaOrders isolated ingress SHALL emit exactly one such
event after each authenticated, signature-valid, canonical-payload-valid
request reaches its existing business decision. The event SHALL use one of
`accepted`, `duplicate`, `rejected` or `unreachable` and SHALL be parseable by
the corresponding operational log reader.

Core pre-decision HTTP branches — unknown or inactive installation, missing or
undecryptable key material, signature failure, and canonical payload
validation/identity mismatch — are transport/authentication/contract failures,
not business outcomes. They SHALL preserve their existing HTTP responses and
SHALL NOT be converted into a new core business-outcome event. When reached
through the adapter, the adapter SHALL observe a core non-2xx response as
`outcome=unreachable`, `reason=core_http_failure`.

#### Scenario: Accepted inbound is distinguishable from transport success

- **WHEN** NovaOrders accepts a new canonical event
- **THEN** the core emits one event with `outcome=accepted`
- **AND** the adapter emits one event with `outcome=accepted`
- **AND** the existing HTTP 200 and empty TwiML response remain unchanged

#### Scenario: Duplicate inbound remains visible

- **WHEN** the coordinator reports an already processed provider message
- **THEN** both edge services emit `outcome=duplicate`
- **AND** no second receipt, processing item or outbound send is created

#### Scenario: Core pre-decision failure remains a transport outcome

- **WHEN** NovaOrders rejects the adapter request before the business
  decision, for example because the installation is inactive, the signature
  is invalid or the canonical payload does not match the installation
- **THEN** NovaOrders preserves its existing non-200 response and does not
  emit a core business-outcome event
- **AND** the adapter emits exactly one event with
  `outcome=unreachable` and `reason=core_http_failure`
- **AND** the adapter preserves its existing HTTP/TwiML response behavior

### Requirement: Rejection reasons use a closed vocabulary

For `rejected` and `unreachable` outcomes, the event SHALL carry exactly one
bounded reason from the documented allowlist: `signature_rejected`,
`invalid_form`, `missing_comercio_id`, `core_http_failure`,
`core_invalid_response`, `unknown_destination`,
`shared_channel_not_supported`, `channel_commerce_mismatch`,
`unknown_client`, `unavailable_commerce` or `invalid_context`. Events SHALL
reject arbitrary reason text and SHALL omit `reason` for `accepted` and
`duplicate`.

#### Scenario: Inactive commerce is diagnosable without a second status code

- **WHEN** the core rejects an otherwise authenticated event because the
  commerce is unavailable
- **THEN** the core and adapter events carry `outcome=rejected` and
  `reason=unavailable_commerce`
- **AND** the existing HTTP 200/TwiML contract is preserved

#### Scenario: Unknown client is distinguished from unknown destination

- **WHEN** the channel resolves but the sender is not an active client
- **THEN** the core event carries `reason=unknown_client`
- **AND** the event does not expose the sender address or message body

### Requirement: Observability cannot alter business behavior

Event emission SHALL occur after the existing typed outcome is determined and
SHALL not open or control a database transaction, call a provider, change a
response, trigger a retry or widen a fallback. An event-builder, serializer or
sink failure SHALL preserve the existing HTTP/TwiML and coordinator behavior.

#### Scenario: Sink failure preserves an accepted event

- **WHEN** the structured event sink cannot serialize or write an accepted
  outcome
- **THEN** the inbound request still returns the existing successful response
- **AND** the durable receipt and deferred work behavior is unchanged

### Requirement: Events are privacy-safe and operationally parseable

Events SHALL contain only the event name, schema version, component, timestamp,
outcome and bounded reason/status metadata. They SHALL NOT contain message
body, phone number, provider payload, provider/message identifier, installation
or commerce identifier, signature, credential, token, URL, LLM content, raw
exception text or arbitrary user input. Core events SHALL use the existing
versioned JSON event catalogue. For this event, the operational parser SHALL
accept exactly `component=commerce_installation_ingress` and
`component=commerce_installation_adapter`; adapter events SHALL remain
backend-independent while using the same event name and outcome vocabulary.

#### Scenario: Sensitive inbound data never reaches the event line

- **WHEN** an inbound form contains a body, phone, profile name and Twilio
  signature
- **THEN** the emitted event contains none of those values
- **AND** the event remains valid under the operational log parser

#### Scenario: Both edge components remain queryable

- **WHEN** the operational log parser receives a valid event from either edge
  component
- **THEN** it accepts `commerce_installation_ingress` and
  `commerce_installation_adapter`
- **AND** it rejects an event carrying any other component for this event
