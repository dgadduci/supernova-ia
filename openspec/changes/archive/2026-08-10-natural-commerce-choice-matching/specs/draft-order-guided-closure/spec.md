# Delta for draft-order-guided-closure

## ADDED Requirements

### Requirement: Natural choice wording remains scoped and ambiguity-safe

After failing exact normalized code/description matching, payment and delivery selection SHALL consider only active candidates already linked to the session commerce. A candidate description qualifies only when every normalized description token appears as a whole token in the customer text. Exactly one qualifying candidate may be selected; zero remains `not_active` and more than one remains `ambiguous`, with no mutation.

#### Scenario: Payment phrase includes harmless wording

- **WHEN** the only active commerce payment description is `Efectivo (prueba cierre)`
- **AND** the customer sends `Pago en Efectivo (prueba cierre)`
- **THEN** the payment is selected
- **AND** no candidate outside that commerce is considered

#### Scenario: Natural wording matches multiple scoped options

- **WHEN** more than one active commerce candidate has all of its description tokens present in the customer text
- **THEN** the result is `ambiguous`
- **AND** the pedido field remains unchanged

#### Scenario: Code fragments and foreign options do not qualify

- **WHEN** the text contains only a partial candidate token or refers to an inactive or commerce-foreign option
- **THEN** it is not selected through the fallback
- **AND** the pedido field remains unchanged
