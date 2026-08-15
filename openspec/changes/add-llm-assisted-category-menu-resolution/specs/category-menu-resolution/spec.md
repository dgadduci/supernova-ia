## ADDED Requirements

### Requirement: Category browsing reuses `ver_menu` and a bounded secondary interpreter

When the existing primary classifier emits `ver_menu` and no pending context
owns the turn, the system SHALL load the sellable catalog only for
`session.id_comercio`. It SHALL derive an ordered, bounded list of visible
category candidates from that same result and invoke one dedicated category
resolver only for this menu turn. The resolver prompt SHALL contain only the
classified menu text and opaque `token` / exact `nombre` candidate pairs; it
SHALL NOT contain database IDs, product names, prices, customer data, pedido
data, aliases, settings, credentials or provider data.

#### Scenario: Natural category browse renders only that commerce category

- **WHEN** a customer asks `qué gustos de empanadas tenés`
- **AND WHEN** the first classifier returns `ver_menu`
- **AND WHEN** the category resolver returns the exact allowed pair for
  `Empanadas`
- **THEN** the system renders only sellable Empanadas from that session's
  commerce with an `Empanadas disponibles:` heading
- **AND THEN** it does not render products from other categories or commerces.

### Requirement: Backend validation, not the LLM, authorizes category filtering

The category resolver SHALL return either both `token` and `nombre` or neither.
The backend SHALL accept selection only when both values exactly match the
same one candidate built for the current commerce invocation. The backend
alone SHALL translate that candidate to its database identity and filter the
already-loaded sellable catalog. It SHALL not trust an LLM-provided database
ID or query another commerce.

#### Scenario: Mismatched token and name cannot select a category

- **WHEN** the category resolver returns a token belonging to `Pizzas` and the
  name `Empanadas`
- **THEN** the selection is invalid
- **AND THEN** the system renders the existing full-menu fallback without
  filtering, mutating state, or disclosing the invalid resolver payload.

### Requirement: Category resolution fails safely to the existing full menu

When there are no sellable items, too many/oversized category candidates,
no-selection, invalid resolver output, or a documented resolver technical
failure, the system SHALL preserve the existing deterministic `ver_menu`
outcome. It SHALL not turn that condition into a failed order turn, retry,
mutation, pending-context change, or technical customer message.

#### Scenario: Unknown category wording preserves current menu behavior

- **WHEN** the menu resolver returns no-selection for an unknown category
  phrase
- **THEN** the response is the existing full current-commerce menu
- **AND THEN** the session, pedido, lines, pending state and transaction state
  are unchanged.
