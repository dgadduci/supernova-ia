## ADDED Requirements

### Requirement: Commerce payment configuration in the browser panel

The authenticated administrative panel SHALL provide a commerce-scoped way to
configure payment associations using only globally active `MediosPago` rows.
For an exact commerce and globally active payment row, the operator SHALL be
able to create/enable or disable that commerce's unique `ComercioMedioPago`
association. A missing association SHALL be created only by a valid enable
operation; disabled missing rows SHALL NOT be created automatically.

#### Scenario: Enable a payment method for one commerce

- **WHEN** an authenticated operator submits a valid enable form for globally
  active payment method M under commerce A
- **THEN** the panel creates or updates only `(A, M)` and redirects to A's
  detail page
- **AND** no association of commerce B is read or mutated

#### Scenario: Disable preserves payment details

- **WHEN** an operator disables an existing commerce payment association that
  has a titular or alias
- **THEN** the association becomes inactive
- **AND** its stored titular and alias remain unchanged

### Requirement: Global payment flags govern commerce form fields

The panel SHALL render and accept `titular` only when the selected global
payment row has `habilita_titular=true`, and analogously for `alias`. A
disabled field SHALL not be made required, cleared, or accepted through a
tampered submission.

#### Scenario: Disabled alias is preserved against a forged edit

- **WHEN** a global payment row has `habilita_alias=false`, its commerce
  association already has an alias, and a POST contains a different alias
- **THEN** the operation is rejected with bounded feedback
- **AND** the stored alias remains unchanged

### Requirement: Commerce delivery configuration in the browser panel

The authenticated panel SHALL provide a commerce-scoped way to configure
globally active `MetodosEntrega` rows. It SHALL create/enable or disable only
the exact `ComercioMetodoEntrega` association and SHALL validate a
commerce-specific integer `orden >= 0` for every enabled creation or order
edit. Disabling SHALL preserve the association's existing order.

#### Scenario: Configure delivery order for one commerce

- **WHEN** an operator submits a valid enabled delivery configuration for
  globally active method D and commerce A with `orden=2`
- **THEN** only `(A, D)` is created or updated with order 2
- **AND** the page subsequently lists delivery rows ordered by `(orden, id)`

#### Scenario: Negative delivery order is rejected

- **WHEN** an operator submits a delivery order below zero
- **THEN** the panel does not create or modify a bridge row
- **AND** it renders bounded validation feedback

### Requirement: Panel payment and delivery mutations are protected

Every state-changing payment/delivery panel request SHALL retain browser Basic
authentication, same-origin validation, and a CSRF nonce bound to its exact
POST path. It SHALL use POST/redirect/GET and autoescape rendered feedback.

#### Scenario: Cross-origin or invalid-nonce mutation is rejected

- **WHEN** a payment or delivery POST lacks a valid exact-path nonce or has a
  disallowed Origin
- **THEN** no bridge association is created or changed
