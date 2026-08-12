# Capability: intent-classifier

## ADDED Requirements

### Requirement: Order observation vs delivery method boundary

The system SHALL document, in the static prompt template of
`IntentClassifier`, a numbered rule that gives explicit priority to
`set_direccion_entrega` for a concrete address, distinguishes
`set_metodo_de_entrega` from `set_observacion_pedido`, and preserves
the existing address contract. A street, number, neighborhood, city,
or other concrete domicile/address SHALL be `set_direccion_entrega`,
not `set_observacion_pedido`. `set_metodo_de_entrega` is reserved for
selecting or changing the modality of reception (delivery / home
delivery, pickup at the shop, dine-in / consumir en salón). Instructions
that do not establish an address—access, route of entry, portón,
timbre, building, security, pets, care, or another operational
indication—SHALL be `set_observacion_pedido`, even when the message
contains the word "entrega". The rule SHALL preserve the existing
substring-literal, `no inventes`, `no reutilices`, and
`una única acción → exactamente un intent` contracts. The rule SHALL
NOT introduce a new intent name, a new field, a new dispatcher path,
a keyword heuristic, a second classifier, a second LLM call, or any
change to the model, transport, settings, enum, schema, dispatcher,
pending context, persistence of `Pedido`, observations persistence,
order mapper, outbox, transactions, product recognition, migrations,
endpoints, workers, Railway configuration, or deploy.

#### Scenario: Access / route / pets messages route to set_observacion_pedido

- **WHEN** the static prompt is rendered for the customer message
  `La entrega es por el portón lateral` or `Cuidado con el perro`
- **THEN** the rendered prompt documents the new numbered rule and
  the example for that customer message routes it to
  `set_observacion_pedido`

#### Scenario: Modality selection routes to set_metodo_de_entrega

- **WHEN** the static prompt is rendered for the customer message
  `Quiero envío a domicilio` or `Lo retiro por el local`
- **THEN** the rendered prompt documents the new numbered rule and
  the example for that customer message routes it to
  `set_metodo_de_entrega`

#### Scenario: Concrete address retains delivery-address priority

- **WHEN** the static prompt is rendered for `Me lo envias a Tilcara 2020`
- **THEN** it documents that the message is `set_direccion_entrega`
- **AND** it does not reinterpret the address as `set_observacion_pedido`

### Requirement: Calibration corpus pins delivery boundary and address fixtures

The controlled corpus `CONTROLLED_INTENT_CORPUS` SHALL include the four
boundary fixtures and one concrete-address regression that pin the
contract. Each fixture SHALL carry
the exact customer message as its `message`, SHALL pin exactly one
expected intent (`SET_OBSERVACION_PEDIDO` for the two access / care
fixtures, `SET_METODO_DE_ENTREGA` for the two modality fixtures), and
SHALL keep the existing substring-literal contract: the rendered
prompt must contain the fixture message verbatim. The fixtures SHALL
follow the existing regression fixture naming convention
(`F-REG-<slug>`). The corpus SHALL remain safe to render in the
prompt and safe to serialize in the audit report; no fixture SHALL
introduce real customer PII or secrets.

#### Scenario: Two access / care fixtures pin set_observacion_pedido

- **WHEN** the controlled audit runs the
  `La entrega es por el portón lateral` and `Cuidado con el perro`
  fixtures
- **THEN** each fixture pins exactly one intent equal to
  `set_observacion_pedido`

#### Scenario: Two modality fixtures pin set_metodo_de_entrega

- **WHEN** the controlled audit runs the
  `Quiero envío a domicilio` and `Lo retiro por el local` fixtures
- **THEN** each fixture pins exactly one intent equal to
  `set_metodo_de_entrega`

#### Scenario: Boundary fixtures are substrings of their rendered prompts

- **WHEN** each of the four boundary fixtures is rendered through
  `IntentClassifier._build_prompt`
- **THEN** the customer `message` is present verbatim in the rendered
  prompt

#### Scenario: Concrete-address fixture retains set_direccion_entrega

- **WHEN** the controlled audit runs `Me lo envias a Tilcara 2020`
- **THEN** it pins exactly one `set_direccion_entrega` intent
