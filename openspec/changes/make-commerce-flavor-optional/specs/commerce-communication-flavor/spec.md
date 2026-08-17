# Commerce Communication Flavor Specification

## ADDED Requirements

### Requirement: A commerce flavor assignment is optional

The system SHALL allow `Comercio.flavor_comunicacion_id` to be absent. An
absent value SHALL mean that the commerce has no selected presentation flavor,
not that it selects a catalog row with a special code.

#### Scenario: Commerce without flavor remains deterministic

- **WHEN** a commerce has no flavor assignment
- **THEN** the outbound styler makes no LLM request
- **AND THEN** local and provider outputs retain exact deterministic text
- **AND THEN** the closed styling diagnostic reports the existing
  `not_attempted` outcome without a flavor code.

### Requirement: Existing neutral sentinel assignments migrate to absence

The migration SHALL convert only assignments to the canonical global flavor
whose code is `neutro` into an absent commerce assignment. It SHALL preserve
every other flavor assignment and retain foreign-key integrity.

#### Scenario: Non-neutral flavor survives migration

- **WHEN** a commerce is assigned an active non-neutral flavor before upgrade
- **THEN** its same flavor assignment remains after upgrade
- **AND THEN** it retains existing bounded styling behavior.

### Requirement: Assignment boundary supports explicit clearing

The existing authenticated commerce flavor assignment boundary SHALL support
an explicit absent assignment without using zero, empty strings, or a magic
flavor code. It SHALL retain the existing validation for positive assignments
to active global flavors.

#### Scenario: Clearing a selected flavor

- **WHEN** an authenticated administrator explicitly clears a commerce flavor
- **THEN** the relation is persisted as absent
- **AND THEN** later eligible responses are deterministic with no style call
- **AND THEN** no instruction content or internal identifiers are exposed.
