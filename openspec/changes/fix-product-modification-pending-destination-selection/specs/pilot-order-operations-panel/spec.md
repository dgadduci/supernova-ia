## MODIFIED Requirements

### Requirement: Detail exposes safe pending-context execution state

The exact order detail SHALL render a typed execution-state summary for its
own Session. It SHALL show only `context_type`, pending encoding validity,
active intent/status, candidate count, requirement state counts, queue length,
parsed pending-schema version and a closed context/pending consistency value.
It SHALL never render raw `pending_intents`, source text, resolved values,
candidate identifiers/labels, raw queue entries, diagnostics, exception
detail, environment/configuration values, tokens or provider secrets.

For a valid active `modificar_producto` pending intent, the active-intent
value SHALL be admitted as `modificar_producto`. Its candidate count SHALL be
derived only from the stage-relevant persisted candidate list: source list at
`source_selection`, destination list at `destination_selection`. The count
must not expose the list or any resolved value. A valid supported modification
context/status with this projection SHALL report `consistent`.

#### Scenario: Destination modification pending is represented faithfully

- **WHEN** the selected Session has valid `product_modification` pending work
  with active `modificar_producto`, `stage="destination_selection"`, and two
  persisted destination candidate IDs
- **THEN** the page shows active intent `modificar_producto`, candidate count
  `2`, active status `pending_resolution`, and consistency `consistent`
- **AND THEN** it renders none of the IDs, source text, product labels,
  quantity, or raw pending JSON
