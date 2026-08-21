# Capability: T-C emulator inbound signature authentication

## MODIFIED Requirements

### Requirement: Twilio inbound requests SHALL use the provider-mode credential

The T-C adapter SHALL validate the complete Twilio webhook form with the
credential corresponding to its explicit provider mode. In `real` mode it SHALL
use `TC_TWILIO_AUTH_TOKEN`; in `emulator` mode it SHALL use
`TC_TWILIO_EMULATOR_AUTH_TOKEN`. It SHALL never retry validation with the other
credential or fall back between modes.

#### Scenario: Real mode preserves the existing signature contract

- WHEN the provider mode is `real` or omitted
- AND the form is signed with the real Twilio credential
- THEN the existing validation and downstream path remain unchanged
- AND a signature produced only with the emulator credential is rejected with HTTP 403

#### Scenario: Emulator mode accepts the synthetic signature

- WHEN the provider mode is `emulator`
- AND the form is signed with the emulator credential
- THEN the T-C accepts the request and continues through the existing canonical and NovaOrders path
- AND no real Twilio SDK or endpoint is used

#### Scenario: Emulator mode rejects the real credential

- WHEN the provider mode is `emulator`
- AND the form is signed with the real Twilio credential instead
- THEN the existing HTTP 403 behavior is returned
- AND routing, forwarding, and the coordinator are not invoked

#### Scenario: Missing emulator credential fails closed

- WHEN the provider mode is `emulator` without a valid `TC_TWILIO_EMULATOR_AUTH_TOKEN`
- THEN the existing configuration validation rejects startup or request processing before an inbound request is accepted
- AND the real credential is not substituted
