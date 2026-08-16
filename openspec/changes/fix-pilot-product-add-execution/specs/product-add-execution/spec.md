## ADDED Requirements

### Requirement: Modern product add is staged in the caller transaction

The modern `agregar_producto` handler SHALL use a dedicated caller-owned
service seam that validates the active session's own `borrador` Pedido,
selected presentation, positive quantity and exactly one current price before
staging one create or increment. The seam SHALL NOT commit, rollback, begin,
close, refresh or flush. It SHALL NOT select a presentation outside the
resolved candidate set or infer a price.

#### Scenario: Resolved priced presentation creates one line

- **WHEN** `Grande` resolves to a selected candidate of the active session's
  own draft Pedido and that presentation has exactly one current price
- **THEN** the handler returns `executed` and stages one line with that price
  snapshot
- **AND** the outer provider transaction remains the only transaction owner

#### Scenario: Missing or ambiguous price rejects without mutation

- **WHEN** the selected presentation has zero or more than one current price
- **THEN** the handler returns `rejected`, creates or changes no order line
- **AND** it does not choose another price or presentation

### Requirement: Legacy product-add transaction contract remains isolated

The dedicated modern seam SHALL NOT change existing public `add_or_increment`
behavior used by legacy callers. The modern handler SHALL NOT invoke that
legacy transaction-owning method.

#### Scenario: Modern provider turn does not commit during handler execution

- **WHEN** the real provider coordinator processes a successful selected
  product turn
- **THEN** no handler/service transaction-control call occurs before the
  coordinator commits the complete turn

### Requirement: Repeated exact product adds preserve the durable cumulative quantity

For the same active Session, its own `borrador` Pedido and the same exact
selected presentation, each successful `agregar_producto` turn SHALL add the
requested positive quantity to the existing durable line. The returned
`cantidad_final` SHALL equal that persisted total, while the requested amount
remains only the added delta. The local-test order-lines snapshot SHALL render
that persisted total and SHALL NOT derive it from customer-response text or
browser-local arithmetic.

#### Scenario: Three sequential adds use one line and cumulative totals

- **WHEN** a priced exact presentation is added with quantities `1`, then `2`,
  then `3` in three completed turns for the same active draft
- **THEN** the first turn creates one line at `1`, the second makes it `3`,
  and the third makes it `6`
- **AND THEN** each success response reports its durable final quantity (`1`,
  `3`, `6`)
- **AND THEN** the post-turn local-test snapshot contains exactly that one
  line at `6`

#### Scenario: Sequential add failure does not replace a durable line

- **WHEN** a repeated add fails a pre-mutation business guard or raises an
  unexpected technical failure
- **THEN** it does not reset, replace, duplicate or otherwise change the
  existing line
- **AND THEN** existing typed rejection or outer rollback behavior applies

### Requirement: Product-add confirmation distinguishes delta from durable total

For an executed modern `agregar_producto` intent with valid
`cantidad_agregada` and `cantidad_final`, the deterministic customer response
SHALL describe the added delta. When the final line total differs from that
delta, it SHALL also state the resulting total without describing it as newly
added. The response builder SHALL not query or mutate state. An executed
legacy intent lacking `cantidad_agregada` SHALL retain the existing
final-quantity wording; invalid quantities retain the existing generic
technical fallback.

#### Scenario: Incrementing six units by one states one added and seven total

- **WHEN** an exact presentation has a durable line quantity of `6` and an
  executed modern add carries `cantidad_agregada=1` and `cantidad_final=7`
- **THEN** the deterministic response states that one unit was added
- **AND THEN** it states that the line now has seven units
- **AND THEN** it does not state that seven units were added.

#### Scenario: Newly created line remains concise

- **WHEN** an executed modern add carries equal valid delta and final values
- **THEN** the deterministic response retains the concise existing add
  confirmation without a redundant total clause.
