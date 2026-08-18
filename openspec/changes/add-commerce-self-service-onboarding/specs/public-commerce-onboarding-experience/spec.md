## ADDED Requirements

### Requirement: Public landing introduces the self-service trial clearly

The system SHALL expose a public, server-rendered landing that explains the
NovaOrders value proposition, the free-trial journey and one clear registration
CTA without querying or disclosing commerce, order, administrative or provider
data. The page SHALL be responsive, semantic, keyboard navigable, readable
without client-side JavaScript and meet WCAG AA contrast requirements.

#### Scenario: Visitor begins free-trial registration

- **WHEN** an unauthenticated visitor selects the landing's primary CTA
- **THEN** the system SHALL navigate to the passwordless email request surface
- **AND THEN** it SHALL not create a commerce, order, channel or trial quota
  reservation

#### Scenario: Essential landing interaction is accessible

- **WHEN** a visitor uses only a keyboard at a narrow viewport
- **THEN** the primary CTA and all essential links SHALL have visible focus,
  readable labels and a usable layout
- **AND THEN** essential content SHALL not depend on hover or autoplaying media

### Requirement: Onboarding presentation communicates progress and safe next actions

The authenticated owner onboarding surface SHALL present concise progress,
field-local escaped validation feedback and derived readiness next actions. It
SHALL distinguish draft completion, review pending and trial status without
claiming a commerce is able to receive orders before the authoritative
readiness/lifecycle conditions are met.

#### Scenario: Incomplete basic data is shown without losing progress

- **WHEN** an owner submits invalid or incomplete basic commerce data
- **THEN** the system SHALL preserve the authorized draft and show bounded
  feedback beside the affected fields
- **AND THEN** it SHALL not create a partial `Comercio` or owner membership
