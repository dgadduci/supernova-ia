## ADDED Requirements

### Requirement: Ready product-line observation execution

When the authoritative active ready intent has
`handler == "set_observacion_producto"`, pending-context execution SHALL
invoke its dedicated handler once. For a definitive `executed` or `rejected`
outcome it SHALL clear the non-queued order-line context; for `failed` it
SHALL preserve active state and propagate according to the existing transaction
boundary. It SHALL not commit or roll back.

#### Scenario: Resolved observation closes its clarification context

- **WHEN** an order-line clarification makes an observation intent ready and
  its handler executes successfully
- **THEN** the result is returned once and pending state/context are cleared
