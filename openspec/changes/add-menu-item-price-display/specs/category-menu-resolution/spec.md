## MODIFIED Requirements

### Requirement: Category browsing reuses `ver_menu` and a bounded secondary interpreter

When the existing primary classifier emits `ver_menu` and no pending context
owns the turn, the system SHALL load the sellable catalog only for
`session.id_comercio`. It SHALL derive an ordered, bounded list of visible
category candidates from that same result and invoke one dedicated category
resolver only for this menu turn. The resolver prompt SHALL contain only the
classified menu text and opaque `token` / exact `nombre` candidate pairs; it
SHALL NOT contain database IDs, product names, prices, customer data, pedido
data, aliases, settings, credentials or provider data. Each rendered menu
item SHALL include its current valid presentation price in stable two-decimal
form when that already-loaded sellable catalog item has one; otherwise it
shall retain the item without a price.

#### Scenario: Natural category browse renders only that commerce category with valid prices

- **WHEN** a customer asks `qué gustos de empanadas tenés`
- **AND WHEN** the first classifier returns `ver_menu`
- **AND WHEN** the category resolver returns the exact allowed pair for
  `Empanadas`
- **THEN** the system renders only sellable Empanadas from that session's
  commerce with an `Empanadas disponibles:` heading
- **AND THEN** every item with a valid current price is rendered as product,
  presentation and its stable two-decimal price
- **AND THEN** it does not render products from other categories or commerces.

### Requirement: Menu price presentation degrades per item without changing menu resolution

The deterministic `ver_menu` projection SHALL use only the price relation
already available on its current-commerce sellable presentation. Missing,
malformed, or negative prices SHALL omit the price only for the affected item.
They SHALL NOT trigger an LLM call, a second catalog query, a category
selection change, a failed response, a mutation, or a transaction control.

#### Scenario: A price-less item remains visible without an invented price

- **WHEN** a selected category contains one sellable presentation with no
  valid current price and another with a valid price
- **THEN** the price-less presentation is rendered in the existing
  product/presentation form without a price
- **AND THEN** the valid-price presentation includes its stable price
- **AND THEN** the category menu remains successful and read-only.
