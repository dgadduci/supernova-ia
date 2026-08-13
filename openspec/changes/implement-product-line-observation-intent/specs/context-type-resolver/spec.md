## ADDED Requirements

### Requirement: Pending product-line observation uses order-line selection

`resolve_context_type` SHALL return `ContextType.ORDER_LINE_SELECTION` for a
`pending_resolution` `set_observacion_producto` intent with non-empty
`candidate_ids`. It SHALL preserve its existing behavior for every other
intent and remain pure.

#### Scenario: Ambiguous observation gets the existing restricted context

- **WHEN** an observation intent is pending with candidate ids `[10, 11]`
- **THEN** its resolved context type is `order_line_selection`
