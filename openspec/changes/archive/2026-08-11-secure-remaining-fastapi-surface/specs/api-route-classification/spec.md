# API route classification

## ADDED Requirements

### Requirement: Every registered FastAPI router has an explicit access classification

The application SHALL classify every router registered by `backend.main` as
public operational, public provider ingress, administrative, or already
administrative. Any newly registered router SHALL be administrative unless an
approved specification explicitly declares a narrower public exception.

#### Scenario: No unclassified public router is introduced

- **WHEN** a router is registered by the application
- **THEN** focused inventory coverage identifies its classification
- **AND** an unclassified router cannot silently remain unauthenticated

### Requirement: Only approved public routes remain token-exempt

`/health`, the Twilio inbound webhook, and the Twilio delivery callback SHALL
remain exempt from the administrative token. All other current routers SHALL
be classified administrative or already administrative.

#### Scenario: Health remains available without an administrative credential

- **WHEN** a request reaches `/health` without `X-Admin-Token`
- **THEN** it follows its existing health behavior
- **AND** no administrative-token dependency is evaluated
