## ADDED Requirements

### Requirement: Destination-only quantity survives clarification

Initial orchestration and pending resolution SHALL preserve
`cantidad is None` and `cantidad_destino == M` through source/destination
selection. The existing handler re-read remains the authoritative full-source
amount at execution.

#### Scenario: Destination clarification keeps destination-only amount

- **WHEN** source is unique, destination is ambiguous, and the message says `cambia la napolitana por dos mozzarella`
- **THEN** after `grande` selects one pending destination, execution uses full current source quantity and destination amount 2 without widening candidates
