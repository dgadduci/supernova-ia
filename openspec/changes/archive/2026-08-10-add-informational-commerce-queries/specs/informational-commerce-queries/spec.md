# Informational commerce queries

## ADDED Requirements

### Requirement: Commerce-scoped informational responses

For an approved informational intent with no pending context, the system SHALL return a deterministic response sourced only from the supplied session's commerce. It SHALL not mutate conversation or order state.

#### Scenario: Payment options remain isolated

- **WHEN** the classifier emits `ver_metodos_de_pago`
- **THEN** the system lists only active payment options configured for that session's commerce
- **AND** it does not expose another commerce's options.

#### Scenario: No configured hours are not invented

- **WHEN** the classifier emits `consultar_horarios_comercio`
- **THEN** the system states that hours are not configured
- **AND** it does not invent an opening schedule.

### Requirement: Product information is deterministic and safe

The system SHALL detail a product only when one sellable catalog match is unambiguous in the classified source text. Zero or multiple matches SHALL receive fixed clarification guidance.

#### Scenario: Ambiguous product query

- **WHEN** more than one sellable catalog product matches the source text
- **THEN** the system asks the customer to identify one product
- **AND** it does not choose a candidate or mutate the pending candidate set.

### Requirement: Shared rendering path

Local and provider traffic SHALL render approved informational responses through the existing shared response mapper and preserve its ordering.

#### Scenario: Menu response reaches the outbox

- **WHEN** `ver_menu` is processed from provider traffic
- **THEN** its deterministic response is staged through the existing outbound path
- **AND** the local response path produces the same text for the same processed intent.
