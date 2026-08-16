# outbound-response-styling Specification

## ADDED Requirements

### Requirement: Styling is optional and cannot replace deterministic facts

The system SHALL treat deterministic `CustomerResponse` values as authoritative.
For an active selected flavor other than `neutro`, it MAY make at most one
additional LLM request for an inbound turn containing eligible normal response
types. The request SHALL contain response-type tokens only, not raw customer
text or deterministic response text. The backend SHALL compose any accepted
presentation wrapper around the exact original factual message and SHALL
preserve response order, intent, and status.

#### Scenario: One batch applies only validated wrappers

- **WHEN** a non-neutral active commerce flavor has two eligible normal
  responses in one turn
- **THEN** the system makes at most one styling request for that turn
- **AND THEN** each accepted response contains its original factual message as
  an intact contiguous substring
- **AND THEN** response order, intent, and status are unchanged.

### Requirement: Neutral and unsafe cases preserve the current output exactly

The system SHALL not make a styling request for `neutro`, missing or inactive
flavor configuration, or a turn with no eligible response. It SHALL preserve
the deterministic response exactly when the style client or wrapper contract
fails. Error, rejection, pending/ambiguous, and customer-free-text response
families (including observations, address, payment, and delivery input) SHALL
not be sent to the style LLM and SHALL remain unchanged.

#### Scenario: Styling failure does not affect business outcome

- **WHEN** an eligible response is produced but the style request times out or
  returns an invalid wrapper contract
- **THEN** the customer receives the original deterministic response text
- **AND THEN** the business outcome and caller-owned transaction are unchanged
- **AND THEN** the system does not retry or invoke another LLM request.

### Requirement: Local and provider outbound delivery share the same styling boundary

The local channel and provider outbox staging SHALL use the same shared
response-mapping/styling boundary. Styling SHALL not run a second time during
outbox staging.

#### Scenario: Shared mapper produces identical local and staged text

- **WHEN** the same processed intents are rendered for the local channel and
  staged for provider delivery under a usable non-neutral flavor
- **THEN** the response text and order are identical in both paths
- **AND THEN** no second styling request occurs while rows are staged.

### Requirement: Styling diagnostics preserve privacy

Styling diagnostics SHALL contain only bounded metadata required to observe
attempts, application, fallback, latency, flavor code, and static template
identity. They SHALL NOT contain customer text, factual response text, prompt,
internal flavor instruction, model output, or customer/order/session IDs.

#### Scenario: Failed styling emits only bounded metadata

- **WHEN** a styling request fails
- **THEN** diagnostics identify the bounded failure category and template
  identity
- **AND THEN** they do not expose any raw prompt, message, instruction, or
  business identifier.
