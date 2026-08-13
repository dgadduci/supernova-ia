## ADDED Requirements

### Requirement: Pilot operators can inspect commerce price availability read-only

The existing authenticated pilot operations panel SHALL provide a GET-only,
commerce-isolated catalog diagnostic view. For each active
product/presentation of the selected commerce, it SHALL show an escaped label
and a boolean price-availability state. The state is true only when exactly
one current price exists.

#### Scenario: Selected presentation has no price

- **WHEN** an authorized operator opens the selected commerce catalog view
  and Mozzarella Grande has no current price
- **THEN** the row reports price unavailable
- **AND** no catalog, customer, session, Pedido, provider-message or
  transaction state is changed

#### Scenario: Catalog cannot cross commerce boundary

- **WHEN** an operator requests a commerce catalog view
- **THEN** it contains no presentation belonging to another commerce
- **AND** unauthenticated access remains rejected
