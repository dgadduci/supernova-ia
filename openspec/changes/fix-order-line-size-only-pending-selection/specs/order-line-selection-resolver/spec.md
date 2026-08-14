## ADDED Requirements

### Requirement: Pending removal supports exact owned presentation selection

For a pending `quitar_producto` `order_line_selection`, the resolver SHALL
recognize an exact normalized presentation-code reply only from current active
candidate IDs belonging to `session.id_pedido`. It SHALL compare only the
presentation code and MAY ignore exactly one leading Spanish article (`la`,
`el`, `una`, `un`, `las`, `los`). It SHALL select only when exactly one active
candidate matches and SHALL use the existing ready-intent construction.

It SHALL NOT query a commerce catalog, use fuzzy/semantic/LLM recognition,
select an outside candidate, or mutate session, pedido or line data itself.

#### Scenario: Chica resolves one existing line

- **WHEN** candidates are own `Mozzarella Grande` and `Mozzarella Chica`
- **AND WHEN** the customer replies `Chica` or `la chica`
- **THEN** the resolver returns ready for only the Chica `pedido_producto_id`
- **AND THEN** the existing pending execution owns removal and cleanup.

#### Scenario: Grande resolves only Grande

- **WHEN** the same candidate set is pending
- **AND WHEN** the customer replies `Grande`
- **THEN** the resolver returns ready for only the Grande line.

### Requirement: Presentation-only refinement never broadens or guesses

When exact presentation comparison produces zero or multiple candidates, the
resolver SHALL retain its existing recognizer/intersection path. A phrase with
another product, an outside candidate, missing association or malformed
relation SHALL NOT create a deterministic selection.

#### Scenario: Outside product phrase cannot select by suffix

- **WHEN** candidates are only the two Mozzarella lines
- **AND WHEN** the customer replies `Napolitana chica`
- **THEN** the deterministic path selects nothing
- **AND THEN** existing restricted recognition determines the current
  rejection/no-match outcome without adding candidates.
