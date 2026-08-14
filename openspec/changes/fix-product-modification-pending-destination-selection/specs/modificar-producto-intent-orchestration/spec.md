## MODIFIED Requirements

### Requirement: Destination refinement narrows destination candidates only

When the active intent's `stage == "destination_selection"`, the resolver
SHALL refine `destination_candidate_ids` exclusively against the current
destination candidate set, never broadening back to the full active catalog.
Before generic recognition, it SHALL accept a normalized exact bare
presentation code, optionally preceded by one article (`la`, `el`, `una`,
`un`, `las`, `los`), only when exactly one presentation in the existing
restricted destination catalog matches. It SHALL reuse the existing ready
intent path for that ID. Zero or multiple matches SHALL retain the existing
generic-recognition/intersection fallback without guessing.

#### Scenario: Bare destination presentation resolves inside the pending set

- **WHEN** the active intent has `stage == "destination_selection"`, source
  candidate `[41]`, destination candidates `[101, 102]` whose presentation
  codes are `grande` and `chica`, and the reply is `la chica`
- **THEN** the resolver returns the existing ready modification intent with
  source `41` and destination `102`
- **AND THEN** it does not call generic product recognition or alter quantity

#### Scenario: Bare destination presentation never broadens candidates

- **WHEN** a bare reply has zero or more than one exact match in the current
  restricted destination catalog
- **THEN** the resolver uses its existing generic-recognition fallback
- **AND THEN** it does not add a destination ID outside the persisted list

#### Scenario: Full destination wording keeps its existing path

- **WHEN** the reply is `mozzarella chica`
- **THEN** the existing generic-recognition/intersection path remains
  responsible for selecting the destination
