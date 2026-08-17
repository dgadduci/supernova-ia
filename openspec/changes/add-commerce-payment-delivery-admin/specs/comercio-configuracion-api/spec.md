## ADDED Requirements

### Requirement: Commerce configuration read contract remains observational

The existing `GET /comercios/{comercio_id}/configuracion` contract SHALL
remain read-only and retain its scoped payment and delivery association
projections while browser administration is added. The change SHALL NOT add a
JSON mutation endpoint or alter a `Pedido` as a side effect of an
administrative bridge update.

#### Scenario: Historical order is unchanged after a commerce configuration edit

- **WHEN** an administrator enables, disables, or reorders a commerce bridge
  association after an order already references the global method ID
- **THEN** the order's stored payment/delivery ID remains unchanged
- **AND** the configuration read endpoint still returns only associations for
  the requested commerce
