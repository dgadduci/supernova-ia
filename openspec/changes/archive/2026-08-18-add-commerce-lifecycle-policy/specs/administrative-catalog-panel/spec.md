## ADDED Requirements

### Requirement: Admin configures trial limits only for trial commerce

The authenticated commerce create/edit form SHALL offer state rows marked
selectable by the shared state configuration. When the selected state has
PRUEBA operating mode it SHALL require an exact future deadline and a positive
maximum confirmed-order count. It SHALL show the consumed count as read-only
and retain existing panel CSRF, origin, authentication, escaping, and
bounded-feedback guarantees.

#### Scenario: Trial form rejects incomplete configuration

- **WHEN** an operator submits PRUEBA without a valid deadline or positive
  quota
- **THEN** no commerce mutation occurs
- **AND** the form re-renders with bounded feedback and a fresh nonce

#### Scenario: Admin can extend a current trial without resetting use

- **WHEN** an operator edits deadline or quota for an already PRUEBA commerce
- **THEN** the configured limits change
- **AND** the consumed count remains unchanged
