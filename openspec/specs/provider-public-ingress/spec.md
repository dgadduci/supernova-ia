# provider-public-ingress Specification

## Purpose
TBD - created by archiving change secure-remaining-fastapi-surface. Update Purpose after archive.
## Requirements
### Requirement: Provider signature boundaries remain independent of administrative authentication

The Twilio inbound webhook and delivery callback SHALL retain their existing
signature-validation contracts and SHALL NOT require, inspect, log, or accept
`X-Admin-Token` as an alternative authentication mechanism.

#### Scenario: Valid signed provider ingress does not need an admin token

- **WHEN** a valid Twilio-signed inbound or delivery-callback request omits
  `X-Admin-Token`
- **THEN** it follows its existing signature-governed behavior
- **AND** the administrative-token dependency is not evaluated

